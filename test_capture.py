from mss import MSS
import numpy as np
import cv2


region = {
    "left": 200,
    "top": 100,
    "width": 1200,
    "height": 700
}


with MSS() as sct:
    screenshot = sct.grab(region)

    frame = np.array(screenshot)

    frame = cv2.cvtColor(
        frame,
        cv2.COLOR_BGRA2BGR
    )

    cv2.imwrite("debug.png", frame)


print("Screenshot saved -> debug.png")