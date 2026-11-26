import re

from qfluentwidgets import FluentIcon

from src.icons import Icons
from src.tasks.mixin.common import Common

_ENGLISH_MAILBOX = re.compile(r"\bMail\s*box\b|^\W*Mail\W*$", re.IGNORECASE)
_ENGLISH_CLAIM_ALL = re.compile(r"\b(?:Claim|Collect|Take)\s*All\b", re.IGNORECASE)
_ENGLISH_EMPTY_MAIL = re.compile(
    r"\b(?:No\s+(?:mail|messages|(?:claimable\s+)?(?:attachments|rewards)|rewards\s+to\s+claim)"
    r"|Mailbox\s+is\s+empty|All\s+attachments\s+claimed)\b",
    re.IGNORECASE,
)


class MailTask(Common):
    """收邮件子任务：领取邮箱全部附件，日常任务经 DailyFeature 接入。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "收邮件"
        self.icon = Icons.Collect
        self.group_name = "日常任务"
        self.group_icon = FluentIcon.CALENDAR
        self.description = "前往「邮箱」领取全部邮件附件。"

    def claim_mail(self):
        self.info_set("current_task", "claim_delivery_rewards")
        self.log_info("开始收邮件")
        self.press_key("k")
        english = self.lang.locale == "en_US"
        if english and not self.wait_ocr(
            match=_ENGLISH_MAILBOX, box=self.box_of_screen(0.01, 0.015, 0.35, 0.16), time_out=5
        ):
            self.mark_task_failure("Mailbox did not open")
            return False

        claim_label = _ENGLISH_CLAIM_ALL if english else self.lang.daily_routine_mixin.k_ffb5655a
        claimed = self.wait_click_ocr(
            x=0,
            y=0.84 if english else 0.88,
            to_x=0.30 if english else 0.25,
            to_y=0.97 if english else 0.95,
            match=claim_label,
            time_out=5,
        )
        if claimed:
            confirmed = self.wait_pop_up(time_out=5 if english else 15)
            if english and confirmed:
                self.log_info("Mailbox attachments claimed")
        else:
            confirmed = False
        if not claimed and not english:
            self.log_info("未识别到领取按钮，直接退出收邮件")
            self.press_key("esc")
            return True

        if (
            english
            and not confirmed
            and self.wait_ocr(match=_ENGLISH_EMPTY_MAIL, box=self.box_of_screen(0.05, 0.15, 0.95, 0.95), time_out=2)
        ):
            confirmed = True
            self.log_info("Mailbox has no claimable attachments")
        stage_area = (
            self.wait_ocr(
                match=self.lang.daily_routine_mixin.k_4a2ece6a,
                box=self.box.top_left,
                time_out=4,
                raise_if_not_found=False,
            )
            or []
        )
        if len(stage_area) > 0:
            self.click(x=stage_area[0].x, y=stage_area[0].y + int(self.height * 0.25))
            staging_label = self.lang.daily_routine_mixin.k_3fef35d6
            if english:
                staging_label = [staging_label, _ENGLISH_CLAIM_ALL]
            staging_claimed = self.wait_click_ocr(match=staging_label, box=self.box.center, time_out=5)
            if staging_claimed:
                staging_confirmed = self.wait_pop_up()
                confirmed = confirmed and staging_confirmed
        self.press_key("esc")
        if english and not confirmed:
            self.mark_task_failure("Mailbox reward claim could not be verified")
            return False
        return True

    def run(self):
        self.ensure_main(time_out=420)
        self.run_mail()

    def run_mail(self):
        """收邮件流程，独立运行与被日常执行（DailyFeature）共用。"""
        return self.claim_mail()
