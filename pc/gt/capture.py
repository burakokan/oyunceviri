import threading
import time

from windows_capture import WindowsCapture


class WindowGrabber:
    """Captures a window with Windows.Graphics.Capture and keeps only the newest frame.

    The subtitle area is cropped inside the capture callback, so only a small
    strip is copied per frame. Works while the window is covered by others, but
    not while it is minimized.
    """

    def __init__(self, hwnd, roi=None):
        self.roi = roi
        self.closed = False
        self._cond = threading.Condition()
        self._latest = None
        self._seq = 0

        try:
            cap = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=hwnd)
        except Exception:
            cap = WindowsCapture(cursor_capture=False, window_hwnd=hwnd)

        @cap.event
        def on_frame_arrived(frame, control):
            t = time.perf_counter()
            buf = frame.frame_buffer
            if self.roi:
                h, w = buf.shape[:2]
                x, y, rw, rh = self.roi
                crop = buf[int(y * h):int((y + rh) * h), int(x * w):int((x + rw) * w), :3].copy()
            else:
                crop = buf[:, :, :3].copy()
            with self._cond:
                self._latest = (t, crop)
                self._seq += 1
                self._cond.notify_all()

        @cap.event
        def on_closed():
            with self._cond:
                self.closed = True
                self._cond.notify_all()

        self._control = cap.start_free_threaded()

    def next(self, last_seq, timeout=1.0):
        """Wait for a frame newer than last_seq -> (seq, (t_arrival, bgr)) or (last_seq, None)."""
        with self._cond:
            self._cond.wait_for(lambda: self._seq != last_seq or self.closed, timeout)
            if self._seq == last_seq:
                return last_seq, None
            return self._seq, self._latest

    def stop(self):
        try:
            self._control.stop()
        except Exception:
            pass
