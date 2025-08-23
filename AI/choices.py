from django.db.models import TextChoices


class ScheduleTypeChoices(TextChoices):
    ONE_TIME = "ONE_TIME"
    RECURRING = "RECURRING"


class WeekDayChoices(TextChoices):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


class SessionScheduleTaskStatusChoices(TextChoices):
    STARTED = "STARTED"
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class ChatSessionTypeChoices(TextChoices):
    CHAT = "CHAT"
    BOT_BUILDER = "BOT_BUILDER"
