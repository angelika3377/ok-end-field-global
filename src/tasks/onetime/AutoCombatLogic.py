import sys
import traceback
from contextlib import contextmanager
from math import isfinite
from threading import Event

from ok import TaskDisabledException

from src.config import config as app_config
from src.core.BaseEfTask import BaseEfTask
from src.core.BattleConfig import (
    KEY_COND_ENABLED,
    KEY_COND_SEQUENCE,
    KEY_DAMAGE_ROTATION,
    KEY_INSTANT_LINK,
    KEY_INSTANT_ULT,
    KEY_SKILL_ALLOWLIST,
    KEY_TIMING_ROTATION,
)
from src.core.learning.policy import without_learning
from src.core.rotation_ast import iter_actions, normalize_ast
from src.data.FeatureList import FeatureList as fL
from src.data.skill_allowlist import generate_skill_sequence
from src.data.skill_rotation import (
    generate_auto_rotation,
    generate_damage_rotation,
    rotate_auto_rotation_for_current,
)
from src.image.recommend_skill_detector import get_recommend_skill_detector
from src.tasks.onetime.TimedCombatLogic import TimedCombatLogic


@contextmanager
def combat_stop_hotkey(task):
    """Listen for a manual abort while an automated fight owns the executor."""
    executor = getattr(task, "executor", None)
    owner = getattr(executor, "current_task", None)
    if sys.platform != "win32" or owner is None:
        yield
        return

    from pynput.keyboard import GlobalHotKeys

    stopped = Event()

    def stop_combat():
        if stopped.is_set() or executor.current_task is not owner:
            return
        stopped.set()
        owner.disable()
        owner.unpause()
        for trigger in executor.trigger_tasks:
            if trigger is not owner and type(trigger).__name__ == "AutoCombatTask" and trigger.enabled:
                trigger.disable()
        task.log_info("Alt+A pressed. Automated combat stopped for manual control.")

    def physical_key_only(_message, data):
        return not data.flags & 0x10  # LLKHF_INJECTED

    listener = GlobalHotKeys({"<alt>+a": stop_combat}, win32_event_filter=physical_key_only)
    listener.start()
    try:
        yield
    finally:
        listener.stop()
    if stopped.is_set():
        raise TaskDisabledException()


class _TaskProbe:
    """CondProbe 适配器：把 task 的检测方法适配为 rotation_ast 的探针接口。"""

    def __init__(self, task: BaseEfTask):
        self._task = task

    def ult_available(self, n: int) -> bool:
        # 对应 battle_mixin.use_ult 内的 find_one("ult_" + n)
        return bool(self._task.find_one("ult_" + str(n)))

    def link_available(self) -> bool:
        # 对应 battle_mixin.use_link_skill 的检测参数
        return bool(
            self._task.find_one(
                fL.default_link_skill, threshold=0.7, vertical_variance=0.005, horizontal_variance=0.005
            )
        )

    def skill_count(self) -> int:
        return self._task.get_skill_bar_count()


class AutoCombatLogic:
    def __init__(self, task: BaseEfTask):
        self.rotation_active = None
        self.skill_sequence = None
        self.rotation_enabled = None
        self.task = task
        self._normal_attack_hold_enabled = False
        self._exit_pending = False
        self._next_exit_check_time = 0
        self.normal_skill_sequence: list = []
        self.normal_start_trigger: int = 2
        self.normal_skill_index: int = 0
        self._last_search_time = 0
        # 实时条件状态
        self.cond_rotation_enabled = False
        self.cond_ast: list = []
        self._cond_iter = None
        self._cond_probe = None
        # 立即释放开关（本帧无动作时生效）
        self.instant_ult_enabled = False
        self.instant_link_enabled = False
        # 自动排轴（伤害优先循环轴）：识别队伍后生成，覆盖战技+终结技+连携
        self.auto_rotation_enabled = False
        self.auto_rotation_active = False
        self.auto_rotation_sequence: list[str] = []
        self.auto_rotation_index = 0
        # 协议空间检测（热启动判定）：战斗画面出现左上角「撤离」按钮
        # （battle_space_left）即为协议空间——开局终结技全满，轴应包含 ult_N；
        # 未出现则视为普通战斗（冷启动），轴不含 ult，由填充段兜底释放。
        self.protocol_space_detected = False
        # 战技失败暂存：技力不足时保留 token 下帧重试，不推进生成器
        self._pending_skill_token = None
        self._pending_skill_frames = 0  # 已重试帧数

    _SKILL_RETRY_MAX_FRAMES = 5  # 技力不足最大等待帧数（≈0.5s）
    _LOW_RES_WARN_INTERVAL = 5.0  # 低分辨率未进入战斗时警告间隔（秒）
    _SECOND_EXIT_THRESHOLD = 1.0  # 进入战斗后该秒数内退出视为“秒退”（等同未进入战斗）
    _EXIT_CHECK_INTERVAL = 0.5
    _TEAM_DETECT_INTERVAL = 1.0  # 战斗主循环中的队伍识别间隔（秒）
    _TEAM_DETECT_MAX_ATTEMPTS = 6  # 战斗主循环中的队伍识别尝试上限

    def _try_detect_protocol_space(self):
        """Best-effort protocol-space classification without sending input.

        Protocol space is a hot start: every visible team member begins with an
        available ultimate. Reuse battle_mixin's exact per-slot ultimate-ready
        detector first; keep the left-top retreat button as a fallback because
        it is an explicit protocol-space UI marker.
        """
        if self.protocol_space_detected:
            return True

        all_ults_ready = getattr(self.task, "are_all_battle_ults_ready", None)
        if callable(all_ults_ready):
            try:
                if all_ults_ready():
                    self.protocol_space_detected = True
                    self.task.log_info("检测到协议空间热启动：当前队伍终结技全部就绪")
                    return True
            except Exception:
                pass

        find_feature = getattr(self.task, "find_feature", None)
        if callable(find_feature):
            try:
                if find_feature(feature=fL.battle_space_left):
                    self.protocol_space_detected = True
                    self.task.log_info("检测到协议空间特征（左上角撤离按钮）")
                    return True
            except Exception:
                pass
        return False

    def _align_auto_rotation_to_current(self, task, sequence: list[str]) -> list[str]:
        """把自动轴旋转到当前主控角色的段开头（切人图标判定成功时）。

        循环轴起点本无语义，但从站场角色的段开始更自然：第一发战技由当前
        主控释放、首个填充段普攻也来自其自身。判定走
        ``battle_mixin.detect_current_char_index``（0 基槽位），尽力而为——
        无该方法（测试替身）、识别失败（None）或异常时原轴返回，绝不因
        对齐失败阻塞排轴。
        """
        detector = getattr(task, "detect_current_char_index", None)
        if not callable(detector):
            return sequence
        try:
            current_slot = detector()
        except Exception:
            return sequence
        rotated = rotate_auto_rotation_for_current(sequence, current_slot)
        if rotated is not sequence:
            task.log_info(f"自动排轴对齐当前主控: 槽位 {current_slot + 1} 段先手")
        return rotated

    def _build_team_skill_sequence(self, task, team, damage_rotation_enabled):
        """生成队伍技能序列，并按冷/热启动状态初始化自动循环轴。"""
        if not damage_rotation_enabled:
            return generate_skill_sequence(team)
        skill_sequence = generate_damage_rotation(team)
        if not self.rotation_enabled:
            include_ult = self.protocol_space_detected
            if not include_ult:
                task.log_info("冷启动排轴: 未检测到协议空间特征，轴不含终结技（就绪后由普通模式兜底释放）")
            self.auto_rotation_sequence = self._align_auto_rotation_to_current(
                task, generate_auto_rotation(team, include_ult=include_ult)
            )
            self.auto_rotation_index = 0
            self.auto_rotation_active = True
            task.log_info(f"自动排轴已生成（可重复循环）: {self.auto_rotation_sequence}")
        return skill_sequence

    def _poll_combat_exit(self, now):
        if now < self._next_exit_check_time:
            return False
        task = self.task
        task.next_frame()
        self._next_exit_check_time = task.active_time() + self._EXIT_CHECK_INTERVAL
        self._exit_pending = bool(task._check_single_exit_condition())
        if self._exit_pending and task.debug:
            task.screenshot("out_of_combat")
        return task.is_combat_ended(self._exit_pending)

    def _sync_normal_attack_hold(self):
        if self._normal_attack_hold_enabled and not self._exit_pending:
            self.task.active_and_send_mouse_delta(activate=True, only_activate=True)
            self.task.mouse_down(key="left")
        else:
            self.task.mouse_up(key="left")

    def _do_normal_combat_frame(self, allow_digits: bool = True):
        """执行一帧普通战斗逻辑（非排轴模式 / normal_[n] 临时模式共用）。

        Args:
            allow_digits: 是否允许释放数字战技。自动排轴的 normal_[n] 填充段
                          传 False——技力须留给轴上的战技，填充段只保留
                          连携/推荐技能/终结技兜底与普攻回能。
        """
        task = self.task

        # 技能优先级：连携技 > 推荐技能 > 终结技
        if task.use_link_skill():
            return
        if task.use_recommend_skill():
            return
        if task.use_ult():
            return

        if not allow_digits:
            return

        skill_count = task.get_skill_bar_count()
        if skill_count < self.normal_start_trigger:
            task.approach_enemy()
            task.next_frame()
            return

        if self.normal_skill_index >= len(self.normal_skill_sequence):
            self.normal_skill_index = 0

        current_points = skill_count  # 同帧结果必然相同
        if current_points < 1:
            if task.use_ult():
                return
            if current_points < 0 and (task.ocr_lv() or task.has_team_hud() is False):
                self.normal_skill_index = 0
                return
            task.approach_enemy()
            task.next_frame()
            return

        if not task.in_combat():
            return

        skill_key = self.normal_skill_sequence[self.normal_skill_index]
        if str(skill_key) in ("1", "2", "3", "4") and int(skill_key) - 1 in getattr(task, "_squad_dead_slots", set()):
            self.normal_skill_index += 1
            return
        task.send_key(skill_key)  # 确认使用send_key：技能键为游戏固定不可配置键，不经过KeyConfigManager管理
        task.log_info(f"Used skill {skill_key}")
        self.normal_skill_index += 1

    def _periodic_search(self):
        now = self.task.active_time()

        if now - self._last_search_time < 1:
            return

        self._last_search_time = now

        self.task.click(key="middle")

    def _exec_rotation_token(self, token: str, deadline):
        """执行单个排轴 token（普通排轴与实时条件共用）。

        Args:
            token: 动作 token（ult_N / sleep_N / normal_N / e / 1~4）。
            deadline: run() 的全局 deadline，供 normal_ 内嵌循环判断超时。

        Returns:
            tuple[bool, str]: (success, signal)。
                success —— 是否成功执行动作（普通排轴据此推进并刷新 5 秒计时；
                           实时条件不卡住，无论成败都取下一 token）。
                signal —— "" 正常 / "break" 战斗结束需跳出主循环 /
                          "return_false" deadline 到达需 return False。
        """
        task = self.task

        if token.startswith("ult_"):
            ult_sequence = token[4:]
            if task.use_ult(ult_sequence=ult_sequence):
                task.log_info(f"释放终极技 {token}")
                return True, ""
            return False, ""

        if token.startswith("sleep_"):
            sleep_time = float(token[6:])
            task.log_info(f"等待 {sleep_time:.3f} 秒")
            sleep_end = task.active_time() + sleep_time
            while True:
                now = task.active_time()
                if deadline is not None and now >= deadline:
                    task.log_info("自动战斗达到最大等待时间")
                    return True, "return_false"
                if self._poll_combat_exit(now):
                    return True, "break"
                self._sync_normal_attack_hold()
                if now >= sleep_end:
                    return True, ""
                wake_at = min(sleep_end, self._next_exit_check_time)
                if deadline is not None:
                    wake_at = min(wake_at, deadline)
                task.sleep(max(0, wake_at - task.active_time()))

        if token.startswith("normal_"):
            normal_duration = float(token[7:])
            task.log_info(f"临时切换普通战斗 {normal_duration:.3f} 秒")
            self.normal_skill_index = 0
            normal_end_time = task.active_time() + normal_duration
            while (now := task.active_time()) < normal_end_time:
                if deadline is not None and now >= deadline:
                    task.log_info("自动战斗达到最大等待时间")
                    return True, "return_false"
                if self._poll_combat_exit(now):
                    return True, "break"
                self._sync_normal_attack_hold()
                if self._exit_pending:
                    task.sleep(0.1)
                    continue
                self._periodic_search()
                task.approach_enemy()
                task.next_frame()
                _probe_pulse = getattr(task, "probe_pulse", None)
                if callable(_probe_pulse):
                    _probe_pulse()
                self._do_normal_combat_frame(allow_digits=not self.auto_rotation_active)
            task.log_info("普通战斗临时模式结束")
            return True, ""

        if token == "e":
            if task.use_link_skill():
                task.log_info(f"释放连携技 {token}")
                return True, ""
            return False, ""

        # 数字战技 1/2/3/4
        if token in ("1", "2", "3", "4") and int(token) - 1 in getattr(task, "_squad_dead_slots", set()):
            return True, ""
        if task.get_skill_bar_count() >= 1:
            task.send_key(token)  # 确认使用send_key：技能键为游戏固定不可配置键，不经过KeyConfigManager管理
            task.log_info(f"释放技能 {token}")
            return True, ""
        return False, ""

    def _do_conditional_rotation_step(self, deadline) -> tuple[str, bool]:
        """执行实时条件的一个动作 token。

        - 生成器耗尽（一轮遍历完）→ 重建（新一轮，重新求值所有条件）。
        - 战技 digit token 失败（技力不足）→ 暂存，下帧重试同一 token。
        - 其他 token（ult/e/sleep/normal）失败即跳过，不重试。
        - 无超时回退：持续运行至战斗结束。

        Returns:
            tuple[signal, had_action]:
                signal —— "" 正常 / "break" / "return_false"（来自 normal_ 内嵌循环）。
                had_action —— 本帧是否产出了条件动作（供立即释放判断）。
        """
        # 战技重试：上一帧 digit token 因技力不足失败，本帧重试同一 token（上限 15 帧）
        if self._pending_skill_token is not None:
            token = self._pending_skill_token
            self._pending_skill_frames += 1
            if self._pending_skill_frames >= self._SKILL_RETRY_MAX_FRAMES:
                self.task.log_info(f"技力不足超时 {self._pending_skill_frames} 帧，跳过战技 {token}")
                self._pending_skill_token = None
                self._pending_skill_frames = 0
                return "", False

            self._pending_skill_token = None  # 先清掉，若仍失败下面会重设
            success, signal = self._exec_rotation_token(token, deadline)
            if not success and signal == "":
                # 仍然技力不足，继续暂存等待下帧
                self._pending_skill_token = token
                return "", True  # had_action=True 阻断立即释放
            self._pending_skill_frames = 0
            return signal, True

        if self._cond_iter is None:
            self._cond_probe = _TaskProbe(self.task)
            self._cond_iter = iter_actions(self.cond_ast, self._cond_probe)

        try:
            token = next(self._cond_iter)
        except StopIteration:
            # 新一轮：重新求值（场上状态可能已变）；本帧不动作，下帧再取
            self._cond_iter = iter_actions(self.cond_ast, self._cond_probe)
            return "", False

        success, signal = self._exec_rotation_token(token, deadline)
        # 战技失败且非 fatal signal → 暂存重试，不推进生成器
        if not success and signal == "" and token.isdigit():
            self._pending_skill_token = token
            self._pending_skill_frames = 0
        return signal, True

    def _advance_auto_rotation(self):
        """推进自动排轴索引（循环取模）。"""
        self.auto_rotation_index = (self.auto_rotation_index + 1) % len(self.auto_rotation_sequence)

    def _do_auto_rotation_step(self, deadline) -> tuple[str, bool]:
        """执行自动排轴的一个动作 token（可重复循环轴）。

        与手动排轴的差别在于失败语义——自动轴永不卡死：
        - 数字战技（技力不足）→ 暂存重试（上限 15 帧），超时跳过推进；
        - ult_N / e 未就绪 → 立即跳过推进，下一轮循环再试；
        - normal_[n] 填充段必定成功，为循环兜底（期间普攻回技力）。

        Returns:
            tuple[signal, had_action]:
                signal —— "" 正常 / "break" / "return_false"（来自 normal_ 内嵌循环）。
                had_action —— 本帧是否消费了 token（恒 True，阻断立即释放判断）。
        """
        # 战技重试：上一帧 digit token 因技力不足失败，本帧重试同一 token
        if self._pending_skill_token is not None:
            token = self._pending_skill_token
            self._pending_skill_frames += 1
            if self._pending_skill_frames >= self._SKILL_RETRY_MAX_FRAMES:
                self.task.log_info(f"技力不足超时，跳过战技 {token}")
                self._pending_skill_token = None
                self._pending_skill_frames = 0
                self._advance_auto_rotation()
                return "", True

            self._pending_skill_token = None  # 先清掉，若仍失败下面会重设
            success, signal = self._exec_rotation_token(token, deadline)
            if not success and signal == "":
                # 仍然技力不足，继续暂存等待下帧
                self._pending_skill_token = token
                return "", True
            self._pending_skill_frames = 0
            if success:
                self._advance_auto_rotation()
                self.last_rotation_ok_time = self.task.active_time()
            return signal, True

        token = self.auto_rotation_sequence[self.auto_rotation_index]
        success, signal = self._exec_rotation_token(token, deadline)
        if signal in ("break", "return_false"):
            return signal, True
        if success:
            self._advance_auto_rotation()
            self.last_rotation_ok_time = self.task.active_time()
        elif token.isdigit():
            # 技力不足：暂存重试，不推进
            self._pending_skill_token = token
            self._pending_skill_frames = 0
        else:
            # ult_N / e 未就绪：跳过推进，下一轮循环再试
            self.task.log_info(f"{token} 未就绪，跳过")
            self._advance_auto_rotation()
        return "", True

    def _do_instant_release(self):
        """本帧无条件动作时，按开关尝试立即释放终结技 / 连携技。

        优先级：终结技 > 连携技。与 _do_normal_combat_frame 一致使用无参检测+释放。
        """
        task = self.task
        if self.instant_ult_enabled and task.use_ult():
            task.log_info("立即释放终结技")
            return
        if self.instant_link_enabled and task.use_link_skill():
            task.log_info("立即释放连携技")
            return

    def _is_low_resolution(self) -> bool:
        """当前画面分辨率是否低于配置中的最低游戏分辨率。"""
        try:
            height = self.task.height
            width = getattr(self.task, "width", None)
        except (AttributeError, TypeError):
            return False
        min_w, min_h = app_config["supported_resolution"]["min_size"]
        return bool(height) and (height < min_h or (width is not None and width < min_w))

    def _warn_low_resolution_if_due(self):
        """分辨率低于配置最低值且处于“未进入战斗”（含秒退）状态时，每 5 秒警告一次。

        计时状态挂在 task 上，保证触发式调度（AutoCombatTask）与 auto_battle 循环
        （每次新建本实例）都能跨次持续计时。
        """
        task = self.task
        if not self._is_low_resolution():
            return
        now = task.active_time()
        last_warn = getattr(task, "_last_low_res_warn_time", 0.0)
        if now - last_warn >= self._LOW_RES_WARN_INTERVAL:
            task._last_low_res_warn_time = now
            min_w, min_h = app_config["supported_resolution"]["min_size"]
            task.log_warning(f"低于{min_w}x{min_h}自动战斗匹配不良，请切换{min_w}x{min_h}及以上分辨率", notify=True)

    def run(
        self,
        start_sleep: float | None = None,
        no_battle: bool = False,
        deadline: float | None = None,
        *,
        burst_delay: float = 0,
    ):
        # start_sleep is the ignored legacy argument. Daily Tasks opt in via burst_delay.
        self._last_team_detect_time = -self._TEAM_DETECT_INTERVAL
        self._team_detect_attempts = 0
        task = self.task
        task._battle_team = None
        if not task.in_combat(required_yellow=1):
            combo_detector = getattr(task, "_combo_skill_detector", None)
            if combo_detector is not None:
                combo_detector.reset(clear_order=True)
            # 非战斗状态：清标记，下次进入战斗时才会复位推荐技能检测器
            task._recommend_detector_in_combat = False
            now = task.active_time()
            last = getattr(task, "_last_no_combat_log_time", 0)
            if now - last >= 5:
                task._last_no_combat_log_time = now
            # 一直未进入战斗：低于最低支持分辨率时每 5 秒警告一次
            self._warn_low_resolution_if_due()
            task.sleep(0.5)
            return False

        with combat_stop_hotkey(task):
            return self._run_confirmed_combat(burst_delay, no_battle, deadline)

    @without_learning("battle")
    def _run_confirmed_combat(self, burst_delay, no_battle, deadline):
        task = self.task
        # 已确认进入战斗，记录进入时刻（用于“秒退”判定）
        combat_enter_time = task.active_time()
        self.protocol_space_detected = False
        try:
            delay = float(burst_delay or 0)
        except (TypeError, ValueError):
            delay = 0
        if not isfinite(delay) or delay < 0:
            delay = 0
        skills_ready_at = combat_enter_time + delay

        # 非战斗 → 战斗 转换时复位推荐技能检测器，每场战斗仅一次：
        # 上一场结束时可能残留 active 标签（战斗外不调用 detect，不会自复位），
        # 新战斗首个白圈周期才能重新产生上升沿。用 task 上的标记保证
        # auto_battle 在同一场战斗内重入 run() 时不再复位，避免同周期白圈
        # 因 active 被清空而重复触发。
        if not getattr(task, "_recommend_detector_in_combat", False):
            combo_detector = getattr(task, "_combo_skill_detector", None)
            if combo_detector is not None:
                combo_detector.reset(clear_order=True)
            get_recommend_skill_detector().reset()
            task._recommend_detector_in_combat = True

        if task.get_battle_config(KEY_TIMING_ROTATION, False):
            return TimedCombatLogic(task).run(
                start_sleep=max(0, skills_ready_at - task.active_time()),
                no_battle=no_battle,
                deadline=deadline,
            )

        task.exit_check_count = 0
        task._squad_hud_absent_since = None
        self._exit_pending = False
        self._next_exit_check_time = combat_enter_time
        self._last_search_time = combat_enter_time - 1.0

        # 初始化普通战斗配置属性（排轴与普通模式共用）
        self.normal_skill_sequence = task.get_battle_config("技能释放", ["1", "2", "3"])
        self.normal_start_trigger = task.get_battle_config("启动技能点数", 2)
        self.normal_skill_index = 0

        # ── 自动技能列表：标记是否需要后续处理 ──
        _skill_allowlist_enabled = task.get_battle_config(KEY_SKILL_ALLOWLIST, False)
        # 伤害优先排轴：自动技能列表的子选项。启用时识别队伍后生成
        # 「战技+终结技+连携+普攻填充」的可重复循环轴并接管执行；
        # 关闭时仅生成伤害降序的战技槽位列表（普通模式循环释放）。
        _damage_rotation_enabled = _skill_allowlist_enabled and task.get_battle_config(KEY_DAMAGE_ROTATION, True)
        self.auto_rotation_enabled = _damage_rotation_enabled
        self.auto_rotation_active = False
        self.auto_rotation_sequence = []
        self.auto_rotation_index = 0
        self.skill_index = 0

        # 模式初始化：实时条件 > 排轴 > 普通
        # 实时条件优先：启用时自动忽略普通排轴
        self.cond_rotation_enabled = task.get_battle_config(KEY_COND_ENABLED, False)
        self.rotation_enabled = False
        self.rotation_active = True
        self._cond_iter = None
        self._cond_probe = None
        self._pending_skill_token = None

        if self.cond_rotation_enabled:
            raw_ast = task.get_battle_config(KEY_COND_SEQUENCE, [])
            self.cond_ast, warnings = normalize_ast(raw_ast)
            for w in warnings:
                task.log_info(f"实时条件配置警告: {w}")
            if not self.cond_ast:
                task.log_info("实时条件序列为空或全部非法，回退普通模式")
                self.cond_rotation_enabled = False

        # 立即释放开关（仅在实时条件启用时生效）
        self.instant_ult_enabled = self.cond_rotation_enabled and task.get_battle_config(KEY_INSTANT_ULT, False)
        self.instant_link_enabled = self.cond_rotation_enabled and task.get_battle_config(KEY_INSTANT_LINK, False)

        if self.cond_rotation_enabled:
            task.log_info(f"实时条件已启用，AST 节点数={len(self.cond_ast)}（忽略普通排轴）")
            if self.instant_ult_enabled:
                task.log_info("立即释放终结技 已启用")
            if self.instant_link_enabled:
                task.log_info("立即释放连携技 已启用")
        else:
            self.rotation_enabled = task.get_battle_config("启用排轴", False)
            if self.rotation_enabled:
                skill_sequence_config = task.get_battle_config("排轴序列", "")
                task.log_info(f"排轴已启用，排轴序列配置: '{skill_sequence_config}'")
                self.skill_sequence = self.task._parse_skill_sequence(skill_sequence_config)
                self.skill_index = 0
                if not self.skill_sequence:
                    self.rotation_active = False
                self.task.log_info(f"解析后的排轴技能序列: {self.skill_sequence}")
                self.last_rotation_ok_time = max(task.active_time(), skills_ready_at)

        if not no_battle:
            task.log_info("检测到进入战斗,开始自动战斗流程")
            task.log_info(f"战斗配置: 技能序列={self.normal_skill_sequence}, 启动点数={self.normal_start_trigger}")

            if task.debug:
                task.screenshot("enter_combat")
            self._normal_attack_hold_enabled = True

            # 战斗已由 required_yellow=1 的血条门控确认，不再做固定开场等待。
            # 队伍与协议空间识别由下方主循环立即尝试并按间隔重试。

        try:
            while True:
                now = task.active_time()
                if deadline is not None and now >= deadline:
                    task.log_info("自动战斗达到最大等待时间")
                    return False
                if self._poll_combat_exit(now):
                    break
                self._sync_normal_attack_hold()
                if self._exit_pending or no_battle:
                    task.sleep(0.1 if self._exit_pending else 0.5)
                    continue
                self._periodic_search()

                # 按间隔尝试稳定识别队伍，识别成功或达到尝试上限后停止扫描
                team_detect_due = now - self._last_team_detect_time >= self._TEAM_DETECT_INTERVAL
                team_detect_available = self._team_detect_attempts < self._TEAM_DETECT_MAX_ATTEMPTS
                if (
                    not getattr(task, "_battle_team", None)
                    and _skill_allowlist_enabled
                    and team_detect_due
                    and team_detect_available
                ):
                    self._team_detect_attempts += 1
                    if _damage_rotation_enabled:
                        # 战斗中识别尝试时顺带补检协议空间特征
                        self._try_detect_protocol_space()
                    try:
                        team, stable = task.detect_team_stable()
                        if stable and team and any(m != "?" for m in team):
                            skill_sequence = self._build_team_skill_sequence(task, team, _damage_rotation_enabled)
                            task._battle_team, self.normal_skill_sequence = team, skill_sequence
                            task.log_info(f"战斗中识别到队伍: {team}")
                            task.log_info(f"自动技能列表已生成: {self.normal_skill_sequence}")
                    except Exception as exc:
                        task._battle_team = None
                        self.auto_rotation_active = False
                        task.log_info(f"队伍识别或自动技能列表生成失败: {exc}")
                    finally:
                        self._last_team_detect_time = task.active_time()

                task.approach_enemy()
                task.next_frame()

                # 独立脉冲探针：与战斗模式/配置无关，观测后立即继续本帧逻辑
                # （getattr 守卫兼容无 probe_pulse 能力的测试替身）
                _probe_pulse = getattr(task, "probe_pulse", None)
                if callable(_probe_pulse):
                    _probe_pulse()

                if task.active_time() < skills_ready_at:
                    continue

                # ── 模式分发：实时条件 > 普通排轴 > 自动排轴 > 普通 ──────────
                if self.cond_rotation_enabled:
                    signal, had_action = self._do_conditional_rotation_step(deadline)
                    if signal == "return_false":
                        return False
                    if signal == "break":
                        break
                    # 本帧无条件动作产出时，按开关尝试立即释放终结技 / 连携技
                    if not had_action:
                        self._do_instant_release()
                elif self.rotation_enabled and self.rotation_active:
                    if task.active_time() - self.last_rotation_ok_time >= 5:
                        self.rotation_active = False
                        task.log_info("排轴超时，切换为普通模式")
                    now_skill = self.skill_sequence[self.skill_index]
                    success, signal = self._exec_rotation_token(now_skill, deadline)
                    if signal == "return_false":
                        return False
                    if signal == "break":
                        break
                    if success:
                        self.skill_index = (self.skill_index + 1) % len(self.skill_sequence)
                        self.last_rotation_ok_time = task.active_time()
                elif self.auto_rotation_enabled and self.auto_rotation_active:
                    # 自动排轴：循环轴 + 失败跳过推进，不卡轴也不超时退出
                    signal, _ = self._do_auto_rotation_step(deadline)
                    if signal == "return_false":
                        return False
                    if signal == "break":
                        break
                else:
                    self._do_normal_combat_frame()
        except TaskDisabledException:
            raise
        except Exception as exc:
            task.log_info(f"自动战斗发生异常: {exc}")
            task.log_info(traceback.format_exc())
            return True
        finally:
            self._normal_attack_hold_enabled = False
            self._sync_normal_attack_hold()
        task._recommend_detector_in_combat = False
        if task.active_time() - combat_enter_time < self._SECOND_EXIT_THRESHOLD:
            self._warn_low_resolution_if_due()
        task.log_info("自动战斗结束!", notify=task.get_battle_config("完成通知"))
        task.log_info("退出战斗主循环")
        return True
