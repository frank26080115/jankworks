from datetime import datetime

class ProgressTracker(object):
    def __init__(self, alpha:float = 0.8):
        self.alpha = alpha
        self.max_cnt = None
        self.cnt = 0
        self.last_time = None
        self.speed = None

    def on_add(self):
        if self.max_cnt is None:
            self.max_cnt = 1
        else:
            self.max_cnt += 1

    def update_max(self, cnt):
        if self.max_cnt is None:
            self.max_cnt = cnt
        elif cnt > self.max_cnt:
            self.max_cnt = cnt

    def on_inference(self, queue_cnt):
        now = datetime.now()
        self.cnt += 1
        if self.last_time is not None:
            dt = now - self.last_time
            dt = dt.total_seconds()
            if self.speed is None:
                self.speed = dt
            else:
                self.speed = (self.speed * self.alpha) + (dt * (1.0 - self.alpha))
        self.last_time = now
        if self.max_cnt is not None:
            if queue_cnt > self.max_cnt:
                self.max_cnt = queue_cnt

        if self.max_cnt is not None and self.max_cnt < 5:
            return

        if self.max_cnt is not None:
            max_cnt = max(1, self.max_cnt - 1)
            fraction_str = f"{self.cnt}/{max_cnt}"
            percentage = round(100 * (self.cnt / max_cnt))
        else:
            fraction_str = f"{queue_cnt}/???"
            percentage = "???"
        if self.speed is not None:
            time_remaining = queue_cnt * self.speed
            minutes_remaining = time_remaining / 60
            if minutes_remaining > 120:
                time_str = f"({minutes_remaining/60:0.1f} hours remaining)"
            elif time_remaining > 120:
                time_str = f"({minutes_remaining:0.1f} minutes remaining)"
            else:
                time_str = f"({round(time_remaining)} seconds remaining)"
        else:
            time_str = ""
        print(f"Progress: {fraction_str} : {percentage}% {time_str}            \r", end="", flush=True)
