"""
This is the same simple threshold detector that Numenta uses in their NuPIC-based detector implementation.
Hence, this file is for demonstrating how "powerful" it is on NAB.
"""

from nab.detectors.base import AnomalyDetector

SPATIAL_TOLERANCE = 0.05

class ThresholdDetector(AnomalyDetector):
    def __init__(self, *args, **kwargs):
        super(ThresholdDetector, self).__init__(*args, **kwargs)

        self.minVal = None
        self.maxVal = None

    def handleRecord(self, inputData):
        ts = inputData["timestamp"]
        val = inputData["value"]

        spatialAnomaly = 0.0

        # Update min/max values and check if there is a spatial anomaly
        if self.minVal != self.maxVal:
            tolerance = (self.maxVal - self.minVal) * SPATIAL_TOLERANCE
            maxExpected = self.maxVal + tolerance
            minExpected = self.minVal - tolerance
            if val > maxExpected or val < minExpected:
                spatialAnomaly = 1.0
        if self.maxVal is None or val > self.maxVal:
            self.maxVal = val
        if self.minVal is None or val < self.minVal:
            self.minVal = val

        return (spatialAnomaly,)