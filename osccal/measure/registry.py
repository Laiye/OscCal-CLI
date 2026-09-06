from osccal.measure.amp import AmpCalibrator
from osccal.measure.bandwidth import BandwidthCalibrator
from osccal.measure.dc_gain import DcGainCalibrator
from osccal.measure.delta_time import DeltaTimeCalibrator
from osccal.measure.transient import TransientCalibrator

CALIBRATORS_MAP = {
    "amp": AmpCalibrator,
    "dc_gain": DcGainCalibrator,
    "delta_time": DeltaTimeCalibrator,
    "bandwidth": BandwidthCalibrator,
    "transient": TransientCalibrator,
}

CALIBRATOR_ORDER = [
    {"name": "amp", "class": AmpCalibrator},
    {"name": "dc_gain", "class": DcGainCalibrator},
    {"name": "delta_time", "class": DeltaTimeCalibrator},
    {"name": "bandwidth", "class": BandwidthCalibrator},
    {"name": "transient", "class": TransientCalibrator},
]
