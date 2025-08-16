from apscheduler.schedulers.background import BackgroundScheduler
from config import SCHEDULE_EVERY_MIN

def init_scheduler(app, collect_callable):
    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        lambda: collect_callable(app),
        "interval",
        minutes=SCHEDULE_EVERY_MIN,
        id="collect_job",
        replace_existing=True
    )
    scheduler.start()
    return scheduler
