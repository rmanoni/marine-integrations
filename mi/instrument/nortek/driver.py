"""
@package mi.instrument.nortek.driver
@file mi/instrument/nortek/driver.py
@author Bill Bollenbacher
@author Steve Foley
@author Rachel Manoni
@brief Base class for Nortek instruments
"""
from functools import wraps
from mi.core.driver_scheduler import TriggerType, DriverSchedulerConfigKey

__author__ = 'Rachel Manoni'
__license__ = 'Apache 2.0'

import re
import time
import copy
import base64

from mi.core.log import get_logger; log = get_logger()

from mi.core.instrument.instrument_fsm import InstrumentFSM

from mi.core.instrument.data_particle import DataParticle, DataParticleKey, DataParticleValue
from mi.core.instrument.data_particle import CommonDataParticleType
from mi.core.instrument.instrument_protocol import CommandResponseInstrumentProtocol
from mi.core.instrument.driver_dict import DriverDict, DriverDictKey
from mi.core.instrument.protocol_cmd_dict import ProtocolCommandDict
from mi.core.instrument.protocol_param_dict import ParameterDictVisibility
from mi.core.instrument.protocol_param_dict import ProtocolParameterDict
from mi.core.instrument.protocol_param_dict import RegexParameter

from mi.core.instrument.instrument_driver import DriverEvent
from mi.core.instrument.instrument_driver import DriverConfigKey
from mi.core.instrument.instrument_driver import SingleConnectionInstrumentDriver
from mi.core.instrument.instrument_driver import DriverAsyncEvent
from mi.core.instrument.instrument_driver import DriverProtocolState
from mi.core.instrument.instrument_driver import DriverParameter
from mi.core.instrument.instrument_driver import ResourceAgentState

from mi.core.instrument.protocol_param_dict import ParameterDictType

from mi.core.exceptions import ReadOnlyException
from mi.core.exceptions import InstrumentStateException
from mi.core.exceptions import InstrumentTimeoutException
from mi.core.exceptions import InstrumentProtocolException
from mi.core.exceptions import InstrumentParameterException
from mi.core.exceptions import SampleException

from mi.core.time import get_timestamp_delayed
from mi.core.common import BaseEnum

from mi.core.util import dict_equal

from mi.core.instrument.chunker import StringChunker

# newline.
NEWLINE = '\n\r'

# default timeout.
TIMEOUT = 10
# set up the 'structure' lengths (in bytes) and sync/id/size constants   
USER_CONFIG_LEN = 512
USER_CONFIG_SYNC_BYTES = '\xa5\x00\x00\x01'
HW_CONFIG_LEN = 48
HW_CONFIG_SYNC_BYTES = '\xa5\x05\x18\x00'
HEAD_CONFIG_LEN = 224
HEAD_CONFIG_SYNC_BYTES = '\xa5\x04\x70\x00'
CHECK_SUM_SEED = 0xb58c
BV_LEN = 4
ID_LEN = 14

HARDWARE_CONFIG_DATA_PATTERN = r'%s(.{14})(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})(.{12})(.{4})(.{2})' \
                               % HW_CONFIG_SYNC_BYTES
HARDWARE_CONFIG_DATA_REGEX = re.compile(HARDWARE_CONFIG_DATA_PATTERN, re.DOTALL)
HEAD_CONFIG_DATA_PATTERN = r'%s(.{2})(.{2})(.{2})(.{12})(.{176})(.{22})(.{2})(.{2})' % HEAD_CONFIG_SYNC_BYTES
HEAD_CONFIG_DATA_REGEX = re.compile(HEAD_CONFIG_DATA_PATTERN, re.DOTALL)
USER_CONFIG_DATA_PATTERN = r'%s(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})' \
                           r'(.{2})(.{2})(.{2})(.{2})(.{2})(.{6})(.{2})(.{6})(.{4})(.{2})(.{2})(.{2})(.{2})(.{2})' \
                           r'(.{2})(.{2})(.{2})(.{2})(.{180})(.{180})(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})' \
                           r'(.{2})(.{2})(.{2})(.{2})(.{2})(.{2})(.{30})(.{16})(.{2})' % USER_CONFIG_SYNC_BYTES
USER_CONFIG_DATA_REGEX = re.compile(USER_CONFIG_DATA_PATTERN, re.DOTALL)

CLOCK_DATA_PATTERN = r'(.{1})(.{1})(.{1})(.{1})(.{1})(.{1})\x06\x06'
CLOCK_DATA_REGEX = re.compile(CLOCK_DATA_PATTERN, re.DOTALL)
BATTERY_DATA_PATTERN = r'(.{2})\x06\x06'
BATTERY_DATA_REGEX = re.compile(BATTERY_DATA_PATTERN, re.DOTALL)
ID_DATA_PATTERN = r'(.{14})\x06\x06'
ID_DATA_REGEX = re.compile(ID_DATA_PATTERN, re.DOTALL)

RUN_CLOCK_SYNC_REGEX = r"clk\s([0-9][0-9]:[0-9][0-9]:[0-9][0-9])"
ACQUIRE_STATUS_REGEX = r"mc\s([0-9][0-9]:[0-9][0-9]:[0-9][0-9])"

NORTEK_COMMON_SAMPLE_STRUCTS = [[USER_CONFIG_SYNC_BYTES, USER_CONFIG_LEN],
                                [HW_CONFIG_SYNC_BYTES, HW_CONFIG_LEN],
                                [HEAD_CONFIG_SYNC_BYTES, HEAD_CONFIG_LEN]]

NORTEK_COMMON_DYNAMIC_SAMPLE_STRUCTS = []


def log_method(func):
    @wraps(func)
    def inner(*args, **kwargs):
        log.debug('%%% entered %s | args: %r | kwargs: %r', func.__name__, args, kwargs)
        r = func(*args, **kwargs)
        log.debug('%%% exiting %s | returning %r', func.__name__, r)
        return r
    return inner


class ScheduledJob(BaseEnum):
    """
    Scheduled Jobs
    """
    CLOCK_SYNC = 'clock_sync'
    ACQUIRE_STATUS = 'acquire_status'


class NortekDataParticleType(BaseEnum):
    """
    List of particle types
    """
    HARDWARE_CONFIG = 'nortek_hardware_configuration'
    HEAD_CONFIG = 'nortek_head_configuration'
    USER_CONFIG = 'nortek_user_configuration'
    CLOCK = 'nortek_clock_data'
    BATTERY = 'nortek_battery_voltage'
    ID_STRING = 'nortek_identification_string'


class InstrumentPrompts(BaseEnum):
    """
    Device prompts.
    """
    COMMAND_MODE  = 'Command mode'
    CONFIRMATION  = 'Confirm:'
    Z_ACK         = '\x06\x06'  # attach a 'Z' to the front of these two items to force them to the end of the list
    Z_NACK        = '\x15\x15'  # so the other responses will have priority to be detected if they are present


class InstrumentCmds(BaseEnum):
    """
    Instrument Commands
    """
    CONFIGURE_INSTRUMENT               = 'CC'        # sets the user configuration
    SOFT_BREAK_FIRST_HALF              = '@@@@@@'
    SOFT_BREAK_SECOND_HALF             = 'K1W%!Q'
    READ_REAL_TIME_CLOCK               = 'RC'
    SET_REAL_TIME_CLOCK                = 'SC'
    CMD_WHAT_MODE                      = 'II'        # to determine the mode of the instrument
    READ_USER_CONFIGURATION            = 'GC'
    READ_HW_CONFIGURATION              = 'GP'
    READ_HEAD_CONFIGURATION            = 'GH'
    POWER_DOWN                         = 'PD'
    READ_BATTERY_VOLTAGE               = 'BV'
    READ_ID                            = 'ID'
    START_MEASUREMENT_WITHOUT_RECORDER = 'ST'
    ACQUIRE_DATA                       = 'AD'
    CONFIRMATION                       = 'MC'        # confirm a break request
    SAMPLE_AVG_TIME                    = 'A'
    SAMPLE_INTERVAL_TIME               = 'M'
    GET_ALL_CONFIGURATIONS             = 'GA'
    SAMPLE_WHAT_MODE                   = 'I'


class InstrumentModes(BaseEnum):
    """
    List of possible modes the instrument can be in
    """
    FIRMWARE_UPGRADE = '\x00\x00\x06\x06'
    MEASUREMENT      = '\x01\x00\x06\x06'
    COMMAND          = '\x02\x00\x06\x06'
    DATA_RETRIEVAL   = '\x04\x00\x06\x06'
    CONFIRMATION     = '\x05\x00\x06\x06'


class ProtocolState(BaseEnum):
    """
    Protocol states enum.
    """
    UNKNOWN = DriverProtocolState.UNKNOWN
    COMMAND = DriverProtocolState.COMMAND
    AUTOSAMPLE = DriverProtocolState.AUTOSAMPLE
    DIRECT_ACCESS = DriverProtocolState.DIRECT_ACCESS


class ProtocolEvent(BaseEnum):
    """
    Protocol events
    """
    # common events from base class
    ENTER = DriverEvent.ENTER
    EXIT = DriverEvent.EXIT
    GET = DriverEvent.GET
    SET = DriverEvent.SET
    DISCOVER = DriverEvent.DISCOVER
    ACQUIRE_SAMPLE = DriverEvent.ACQUIRE_SAMPLE
    ACQUIRE_STATUS = DriverEvent.ACQUIRE_STATUS
    START_AUTOSAMPLE = DriverEvent.START_AUTOSAMPLE
    STOP_AUTOSAMPLE = DriverEvent.STOP_AUTOSAMPLE
    START_DIRECT = DriverEvent.START_DIRECT
    STOP_DIRECT = DriverEvent.STOP_DIRECT
    EXECUTE_DIRECT = DriverEvent.EXECUTE_DIRECT
    CLOCK_SYNC = DriverEvent.CLOCK_SYNC
    SCHEDULED_CLOCK_SYNC = DriverEvent.SCHEDULED_CLOCK_SYNC
    RESET = DriverEvent.RESET

    # instrument specific events
    SET_CONFIGURATION = "PROTOCOL_EVENT_CMD_SET_CONFIGURATION"
    READ_CLOCK = "PROTOCOL_EVENT_CMD_READ_CLOCK"
    READ_MODE = "PROTOCOL_EVENT_CMD_READ_MODE"
    POWER_DOWN = "PROTOCOL_EVENT_CMD_POWER_DOWN"
    READ_BATTERY_VOLTAGE = "PROTOCOL_EVENT_CMD_READ_BATTERY_VOLTAGE"
    READ_ID = "PROTOCOL_EVENT_CMD_READ_ID"
    GET_HW_CONFIGURATION = "PROTOCOL_EVENT_CMD_GET_HW_CONFIGURATION"
    GET_HEAD_CONFIGURATION = "PROTOCOL_EVENT_CMD_GET_HEAD_CONFIGURATION"
    READ_USER_CONFIGURATION = "PROTOCOL_EVENT_READ_USER_CONFIGURATION"
    SCHEDULED_ACQUIRE_STATUS = "PROTOCOL_EVENT_SCHEDULED_ACQUIRE_STATUS"


class Capability(BaseEnum):
    """
    Capabilities that are exposed to the user (subset of protocol events)
    """
    #TODO - EVERYTHING IS EXPOSED, NEED TO FIND OUT WHAT SHOULD THE OPERATOR HAVE ACCESS TO
    #AND MOST OF THIS IS NOT IMPLEMENTED

    #GET = ProtocolEvent.GET
    #SET = ProtocolEvent.SET
    ACQUIRE_SAMPLE = ProtocolEvent.ACQUIRE_SAMPLE
    RESET = ProtocolEvent.RESET
    #START_AUTOSAMPLE = ProtocolEvent.START_AUTOSAMPLE
    #STOP_AUTOSAMPLE = ProtocolEvent.STOP_AUTOSAMPLE
    CLOCK_SYNC = ProtocolEvent.CLOCK_SYNC
    SET_CONFIGURATION = ProtocolEvent.SET_CONFIGURATION
    #READ_CLOCK = ProtocolEvent.READ_CLOCK
    #READ_MODE = ProtocolEvent.READ_MODE
    #POWER_DOWN = ProtocolEvent.POWER_DOWN
    #READ_BATTERY_VOLTAGE = ProtocolEvent.READ_BATTERY_VOLTAGE
    #READ_ID = ProtocolEvent.READ_ID
    #GET_HW_CONFIGURATION = ProtocolEvent.GET_HW_CONFIGURATION
    #GET_HEAD_CONFIGURATION = ProtocolEvent.GET_HEAD_CONFIGURATION
    #READ_USER_CONFIGURATION = ProtocolEvent.READ_USER_CONFIGURATION


# Device specific parameters.
class Parameter(DriverParameter):
    """
    Instrument parameters
    """
    TRANSMIT_PULSE_LENGTH = "TransmitPulseLength"                # T1
    BLANKING_DISTANCE = "BlankingDistance"                       # T2
    RECEIVE_LENGTH = "ReceiveLength"                             # T3
    TIME_BETWEEN_PINGS = "TimeBetweenPings"                      # T4
    TIME_BETWEEN_BURST_SEQUENCES = "TimeBetweenBurstSequences"   # T5 
    NUMBER_PINGS = "NumberPings"     # number of beam sequences per burst
    AVG_INTERVAL = "AvgInterval"
    USER_NUMBER_BEAMS = "UserNumberOfBeams"
    TIMING_CONTROL_REGISTER = "TimingControlRegister"
    POWER_CONTROL_REGISTER = "PowerControlRegister"
    A1_1_SPARE = 'A1_1Spare'
    B0_1_SPARE = 'B0_1Spare'
    B1_1_SPARE = 'B1_1Spare'
    COMPASS_UPDATE_RATE = "CompassUpdateRate"
    COORDINATE_SYSTEM = "CoordinateSystem"
    NUMBER_BINS = "NumberOfBins"      # number of cells
    BIN_LENGTH = "BinLength"          # cell size
    MEASUREMENT_INTERVAL = "MeasurementInterval"
    DEPLOYMENT_NAME = "DeploymentName"
    WRAP_MODE = "WrapMode"
    CLOCK_DEPLOY = "ClockDeploy"      # deployment start time
    DIAGNOSTIC_INTERVAL = "DiagnosticInterval"
    MODE = "Mode"
    ADJUSTMENT_SOUND_SPEED = 'AdjustmentSoundSpeed'
    NUMBER_SAMPLES_DIAGNOSTIC = 'NumberSamplesInDiagMode'
    NUMBER_BEAMS_CELL_DIAGNOSTIC = 'NumberBeamsPerCellInDiagMode'
    NUMBER_PINGS_DIAGNOSTIC = 'NumberPingsInDiagMode'
    MODE_TEST = 'ModeTest'
    ANALOG_INPUT_ADDR = 'AnalogInputAddress'
    SW_VERSION = 'SwVersion'
    USER_1_SPARE = 'User1Spare'
    VELOCITY_ADJ_TABLE = 'VelocityAdjTable'
    COMMENTS = 'Comments'
    WAVE_MEASUREMENT_MODE = 'WaveMeasurementMode'
    DYN_PERCENTAGE_POSITION = 'PercentageForCellPositioning'
    WAVE_TRANSMIT_PULSE = 'WaveTransmitPulse'
    WAVE_BLANKING_DISTANCE = 'WaveBlankingDistance'
    WAVE_CELL_SIZE = 'WaveCellSize'
    NUMBER_DIAG_SAMPLES = 'NumberDiagnosticSamples'
    A1_2_SPARE = 'A1_2Spare'
    B0_2_SPARE = 'B0_2Spare'
    USER_2_SPARE = 'User2Spare'
    ANALOG_OUTPUT_SCALE = 'AnalogOutputScale'
    CORRELATION_THRESHOLD = 'CorrelationThreshold'
    TRANSMIT_PULSE_LENGTH_SECOND_LAG = 'TransmitPulseLengthSecondLag'
    USER_4_SPARE = 'User4Spare'
    QUAL_CONSTANTS = 'StageMatchFilterConstants'
    NUMBER_SAMPLES_PER_BURST = 'NumberSamplesPerBurst'
    USER_3_SPARE = 'User3Spare'


class EngineeringParameter(DriverParameter):
    """
    Driver Paramters (aka, engineering parameters)
    """
    CLOCK_SYNC_INTERVAL = 'ClockSyncInterval'
    ACQUIRE_STATUS_INTERVAL = 'AcquireStatusInterval'


@log_method
def hw_config_to_dict(input_stream):
    """
    Translate a hardware configuration string into a dictionary, keys being
    from the NortekHardwareConfigDataParticleKey class.
    Should be the result of a GP command
    @retval A dictionary with the translated values
    @throws SampleException If there is a problem with sample creation
    """
    if str(input_stream[-2:]) == InstrumentPrompts.Z_ACK:
        if len(input_stream) != HW_CONFIG_LEN + 2:
            raise SampleException("Invalid input for config! Got input of size %s with an ACK" % len(input_stream))
    else:
        if len(input_stream) != HW_CONFIG_LEN:
            raise SampleException("Invalid input for config!. Got input of size %s with no ACK" % len(input_stream))

    parsed = {NortekHardwareConfigDataParticleKey.SERIAL_NUM: input_stream[4:18],
                NortekHardwareConfigDataParticleKey.CONFIG: NortekProtocolParameterDict.convert_bytes_to_bit_field(input_stream[18:20]),
                NortekHardwareConfigDataParticleKey.BOARD_FREQUENCY: NortekProtocolParameterDict.convert_word_to_int(input_stream[20:22]),
                NortekHardwareConfigDataParticleKey.PIC_VERSION: NortekProtocolParameterDict.convert_word_to_int(input_stream[22:24]),
                NortekHardwareConfigDataParticleKey.HW_REVISION: NortekProtocolParameterDict.convert_word_to_int(input_stream[24:26]),
                NortekHardwareConfigDataParticleKey.RECORDER_SIZE: NortekProtocolParameterDict.convert_word_to_int(input_stream[26:28]),
                NortekHardwareConfigDataParticleKey.STATUS: NortekProtocolParameterDict.convert_bytes_to_bit_field(input_stream[28:30]),
                NortekHardwareConfigDataParticleKey.FW_VERSION: input_stream[42:46],
                NortekHardwareConfigDataParticleKey.CHECKSUM: NortekProtocolParameterDict.convert_word_to_int(input_stream[46:48])}

    return parsed


class NortekHardwareConfigDataParticleKey(BaseEnum):
    """
    Particle key for the hw config
    """
    SERIAL_NUM = 'instmt_type_serial_number'
    RECORDER_INSTALLED = 'recorder_installed'
    COMPASS_INSTALLED = 'compass_installed'
    BOARD_FREQUENCY = 'board_frequency'
    PIC_VERSION = 'pic_version'
    HW_REVISION = 'hardware_revision'
    RECORDER_SIZE = 'recorder_size'
    VELOCITY_RANGE = 'velocity_range'
    FW_VERSION = 'firmware_version'
    STATUS = 'status'
    CONFIG = 'config'
    CHECKSUM = 'checksum'


class NortekHardwareConfigDataParticle(DataParticle):
    """
    Routine for parsing hardware config data into a data particle structure for the Vector sensor. 
    """
    _data_particle_type = NortekDataParticleType.HARDWARE_CONFIG

    @log_method
    def _build_parsed_values(self):
        """
        Use the hardware config data sample format and parse stream into
        values with appropriate tags.
        """
        working_value = hw_config_to_dict(self.raw_data)

        for key in working_value.keys():
            if None == working_value[key]:
                raise SampleException("No %s value parsed", key)

        working_value[NortekHardwareConfigDataParticleKey.RECORDER_INSTALLED] = working_value[NortekHardwareConfigDataParticleKey.CONFIG][-1]
        working_value[NortekHardwareConfigDataParticleKey.COMPASS_INSTALLED] = working_value[NortekHardwareConfigDataParticleKey.CONFIG][-2]
        working_value[NortekHardwareConfigDataParticleKey.VELOCITY_RANGE] = working_value[NortekHardwareConfigDataParticleKey.STATUS][-1]

        # report values
        result = [{DataParticleKey.VALUE_ID: NortekHardwareConfigDataParticleKey.SERIAL_NUM,
                   DataParticleKey.VALUE: working_value[NortekHardwareConfigDataParticleKey.SERIAL_NUM]},
                  {DataParticleKey.VALUE_ID: NortekHardwareConfigDataParticleKey.RECORDER_INSTALLED,
                   DataParticleKey.VALUE: working_value[NortekHardwareConfigDataParticleKey.RECORDER_INSTALLED]},
                  {DataParticleKey.VALUE_ID: NortekHardwareConfigDataParticleKey.COMPASS_INSTALLED,
                   DataParticleKey.VALUE: working_value[NortekHardwareConfigDataParticleKey.COMPASS_INSTALLED]},
                  {DataParticleKey.VALUE_ID: NortekHardwareConfigDataParticleKey.BOARD_FREQUENCY,
                   DataParticleKey.VALUE: working_value[NortekHardwareConfigDataParticleKey.BOARD_FREQUENCY]},
                  {DataParticleKey.VALUE_ID: NortekHardwareConfigDataParticleKey.PIC_VERSION,
                   DataParticleKey.VALUE: working_value[NortekHardwareConfigDataParticleKey.PIC_VERSION]},
                  {DataParticleKey.VALUE_ID: NortekHardwareConfigDataParticleKey.HW_REVISION,
                   DataParticleKey.VALUE: working_value[NortekHardwareConfigDataParticleKey.HW_REVISION]},
                  {DataParticleKey.VALUE_ID: NortekHardwareConfigDataParticleKey.RECORDER_SIZE,
                   DataParticleKey.VALUE: working_value[NortekHardwareConfigDataParticleKey.RECORDER_SIZE]},
                  {DataParticleKey.VALUE_ID: NortekHardwareConfigDataParticleKey.VELOCITY_RANGE,
                   DataParticleKey.VALUE: working_value[NortekHardwareConfigDataParticleKey.VELOCITY_RANGE]},
                  {DataParticleKey.VALUE_ID: NortekHardwareConfigDataParticleKey.FW_VERSION,
                   DataParticleKey.VALUE: working_value[NortekHardwareConfigDataParticleKey.FW_VERSION]}]

        calculated_checksum = NortekProtocolParameterDict.calculate_checksum(self.raw_data)
        if working_value[NortekHardwareConfigDataParticleKey.CHECKSUM] != calculated_checksum:
            log.warn("Calculated checksum: %s did not match packet checksum: %s",
                     calculated_checksum, working_value[NortekHardwareConfigDataParticleKey.CHECKSUM])
            self.contents[DataParticleKey.QUALITY_FLAG] = DataParticleValue.CHECKSUM_FAILED

        log.debug('VectorHardwareConfigDataParticle: particle=%s', result)
        return result


@log_method
def head_config_to_dict(input_stream):
    """
    Translate a head configuration string into a dictionary, keys being
    from the NortekHeadConfigDataParticleKey class.
    Should be the result of a GH command
    @retval A dictionary with the translated values
    @throws SampleException If there is a problem with sample creation
    """
    if str(input_stream[-2:]) == InstrumentPrompts.Z_ACK:
        if len(input_stream) != HEAD_CONFIG_LEN + 2:
            raise SampleException("Invalid input. Got input of size %s with an ACK" % len(input_stream))
    else:
        if len(input_stream) != HEAD_CONFIG_LEN:
            raise SampleException("Invalid input. Got input of size %s with no ACK" % len(input_stream))

    parsed = {NortekHeadConfigDataParticleKey.CONFIG: NortekProtocolParameterDict.convert_bytes_to_bit_field(input_stream[4:6]),
                NortekHeadConfigDataParticleKey.HEAD_FREQ: NortekProtocolParameterDict.convert_word_to_int(input_stream[6:8]),
                NortekHeadConfigDataParticleKey.HEAD_TYPE: NortekProtocolParameterDict.convert_word_to_int(input_stream[8:10]),
                NortekHeadConfigDataParticleKey.HEAD_SERIAL: NortekProtocolParameterDict.convert_bytes_to_string(input_stream[10:22]),
                NortekHeadConfigDataParticleKey.SYSTEM_DATA: base64.b64encode(input_stream[22:198]),
                NortekHeadConfigDataParticleKey.NUM_BEAMS: NortekProtocolParameterDict.convert_word_to_int(input_stream[220:222]),
                NortekHeadConfigDataParticleKey.CHECKSUM: NortekProtocolParameterDict.convert_word_to_int(input_stream[222:224])}

    return parsed


class NortekHeadConfigDataParticleKey(BaseEnum):
    """
    Particle key for the head config
    """
    PRESSURE_SENSOR = 'pressure_sensor'
    MAG_SENSOR = 'magnetometer_sensor'
    TILT_SENSOR = 'tilt_sensor'
    TILT_SENSOR_MOUNT = 'tilt_sensor_mounting'
    HEAD_FREQ = 'head_frequency'
    HEAD_TYPE = 'head_type'
    HEAD_SERIAL = 'head_serial_number'
    SYSTEM_DATA = 'system_data'
    NUM_BEAMS = 'number_beams'
    CONFIG = 'config'
    CHECKSUM = 'checksum'


class NortekHeadConfigDataParticle(DataParticle):
    """
    Routine for parsing head config data into a data particle structure for the Vector sensor. 
    """
    _data_particle_type = NortekDataParticleType.HEAD_CONFIG

    @log_method
    def _build_parsed_values(self):
        """
        Use the head config data sample format and parse stream into
        values with appropriate tags.
        """
        working_value = head_config_to_dict(self.raw_data)
        for key in working_value.keys():
            if None == working_value[key]:
                raise SampleException("No %s value parsed", key)

        working_value[NortekHeadConfigDataParticleKey.PRESSURE_SENSOR] = working_value[NortekHeadConfigDataParticleKey.CONFIG][-1]
        working_value[NortekHeadConfigDataParticleKey.MAG_SENSOR] = working_value[NortekHeadConfigDataParticleKey.CONFIG][-2]
        working_value[NortekHeadConfigDataParticleKey.TILT_SENSOR] = working_value[NortekHeadConfigDataParticleKey.CONFIG][-3]
        working_value[NortekHeadConfigDataParticleKey.TILT_SENSOR_MOUNT] = working_value[NortekHeadConfigDataParticleKey.CONFIG][-4]

        # report values
        result = [{DataParticleKey.VALUE_ID: NortekHeadConfigDataParticleKey.PRESSURE_SENSOR,
                   DataParticleKey.VALUE: working_value[NortekHeadConfigDataParticleKey.PRESSURE_SENSOR]},
                  {DataParticleKey.VALUE_ID: NortekHeadConfigDataParticleKey.MAG_SENSOR,
                   DataParticleKey.VALUE: working_value[NortekHeadConfigDataParticleKey.MAG_SENSOR]},
                  {DataParticleKey.VALUE_ID: NortekHeadConfigDataParticleKey.TILT_SENSOR,
                   DataParticleKey.VALUE: working_value[NortekHeadConfigDataParticleKey.TILT_SENSOR]},
                  {DataParticleKey.VALUE_ID: NortekHeadConfigDataParticleKey.TILT_SENSOR_MOUNT,
                   DataParticleKey.VALUE: working_value[NortekHeadConfigDataParticleKey.TILT_SENSOR_MOUNT]},
                  {DataParticleKey.VALUE_ID: NortekHeadConfigDataParticleKey.HEAD_FREQ,
                   DataParticleKey.VALUE: working_value[NortekHeadConfigDataParticleKey.HEAD_FREQ]},
                  {DataParticleKey.VALUE_ID: NortekHeadConfigDataParticleKey.HEAD_TYPE,
                   DataParticleKey.VALUE: working_value[NortekHeadConfigDataParticleKey.HEAD_TYPE]},
                  {DataParticleKey.VALUE_ID: NortekHeadConfigDataParticleKey.HEAD_SERIAL,
                   DataParticleKey.VALUE: working_value[NortekHeadConfigDataParticleKey.HEAD_SERIAL]},
                  {DataParticleKey.VALUE_ID: NortekHeadConfigDataParticleKey.SYSTEM_DATA,
                   DataParticleKey.VALUE: working_value[NortekHeadConfigDataParticleKey.SYSTEM_DATA],
                   DataParticleKey.BINARY: True},
                  {DataParticleKey.VALUE_ID: NortekHeadConfigDataParticleKey.NUM_BEAMS,
                   DataParticleKey.VALUE: working_value[NortekHeadConfigDataParticleKey.NUM_BEAMS]}]

        calculated_checksum = NortekProtocolParameterDict.calculate_checksum(self.raw_data)
        if working_value[NortekHeadConfigDataParticleKey.CHECKSUM] != calculated_checksum:
            log.warn("Calculated checksum: %s did not match packet checksum: %s",
                     calculated_checksum, working_value[NortekHeadConfigDataParticleKey.CHECKSUM])
            self.contents[DataParticleKey.QUALITY_FLAG] = DataParticleValue.CHECKSUM_FAILED

        log.debug('VectorHeadConfigDataParticle: particle=%s', result)
        return result


@log_method
def user_config_to_dict(input_stream):
    """
    Translate a user configuration string into a dictionary, keys being
    from the NortekUserConfigDataParticleKey class.
    Should be the result of a GC command
    @retval A dictionary with the translated values
    @throws SampleException If there is a problem with sample creation
    """
    # Trim an ACK off the end if we care
    if str(input_stream[-2:]) == InstrumentPrompts.Z_ACK:
        if len(input_stream) != USER_CONFIG_LEN + 2:
            raise SampleException("Invalid input. Got input of size %s with an ACK" % len(input_stream))
    else:
        if len(input_stream) != USER_CONFIG_LEN:
            raise SampleException("Invalid input. Got input of size %s with no ACK" % len(input_stream))

    parsed = {NortekUserConfigDataParticleKey.TX_LENGTH: NortekProtocolParameterDict.convert_word_to_int(input_stream[4:6]),
                NortekUserConfigDataParticleKey.BLANK_DIST: NortekProtocolParameterDict.convert_word_to_int(input_stream[6:8]),
                NortekUserConfigDataParticleKey.RX_LENGTH: NortekProtocolParameterDict.convert_word_to_int(input_stream[8:10]),
                NortekUserConfigDataParticleKey.TIME_BETWEEN_PINGS: NortekProtocolParameterDict.convert_word_to_int(input_stream[10:12]),
                NortekUserConfigDataParticleKey.TIME_BETWEEN_BURSTS: NortekProtocolParameterDict.convert_word_to_int(input_stream[12:14]),
                NortekUserConfigDataParticleKey.NUM_PINGS: NortekProtocolParameterDict.convert_word_to_int(input_stream[14:16]),
                NortekUserConfigDataParticleKey.AVG_INTERVAL: NortekProtocolParameterDict.convert_word_to_int(input_stream[16:18]),
                NortekUserConfigDataParticleKey.NUM_BEAMS: NortekProtocolParameterDict.convert_word_to_int(input_stream[18:20]),
                NortekUserConfigDataParticleKey.TCR: NortekProtocolParameterDict.convert_bytes_to_bit_field(input_stream[20:22]),
                NortekUserConfigDataParticleKey.PCR: NortekProtocolParameterDict.convert_bytes_to_bit_field(input_stream[22:24]),
                NortekUserConfigDataParticleKey.COMPASS_UPDATE_RATE: NortekProtocolParameterDict.convert_word_to_int(input_stream[30:32]),
                NortekUserConfigDataParticleKey.COORDINATE_SYSTEM: NortekProtocolParameterDict.convert_word_to_int(input_stream[32:34]),
                NortekUserConfigDataParticleKey.NUM_CELLS: NortekProtocolParameterDict.convert_word_to_int(input_stream[34:36]),
                NortekUserConfigDataParticleKey.CELL_SIZE: NortekProtocolParameterDict.convert_word_to_int(input_stream[36:38]),
                NortekUserConfigDataParticleKey.MEASUREMENT_INTERVAL: NortekProtocolParameterDict.convert_word_to_int(input_stream[38:40]),
                NortekUserConfigDataParticleKey.DEPLOYMENT_NAME: NortekProtocolParameterDict.convert_bytes_to_string(input_stream[40:46]),
                NortekUserConfigDataParticleKey.WRAP_MODE: NortekProtocolParameterDict.convert_word_to_int(input_stream[46:48]),
                NortekUserConfigDataParticleKey.DEPLOY_START_TIME: NortekProtocolParameterDict.convert_words_to_datetime(input_stream[48:54]),
                NortekUserConfigDataParticleKey.DIAG_INTERVAL: NortekProtocolParameterDict.convert_double_word_to_int(input_stream[54:58]),
                NortekUserConfigDataParticleKey.MODE: NortekProtocolParameterDict.convert_bytes_to_bit_field(input_stream[58:60]),
                NortekUserConfigDataParticleKey.SOUND_SPEED_ADJUST: NortekProtocolParameterDict.convert_word_to_int(input_stream[60:62]),
                NortekUserConfigDataParticleKey.NUM_DIAG_SAMPLES: NortekProtocolParameterDict.convert_word_to_int(input_stream[62:64]),
                NortekUserConfigDataParticleKey.NUM_BEAMS_PER_CELL: NortekProtocolParameterDict.convert_word_to_int(input_stream[64:66]),
                NortekUserConfigDataParticleKey.NUM_PINGS_DIAG: NortekProtocolParameterDict.convert_word_to_int(input_stream[66:68]),
                NortekUserConfigDataParticleKey.MODE_TEST: NortekProtocolParameterDict.convert_bytes_to_bit_field(input_stream[68:70]),
                NortekUserConfigDataParticleKey.ANALOG_INPUT_ADDR: NortekProtocolParameterDict.convert_word_to_int(input_stream[70:72]),
                NortekUserConfigDataParticleKey.SW_VER: NortekProtocolParameterDict.convert_word_to_int(input_stream[72:74]),
                NortekUserConfigDataParticleKey.VELOCITY_ADJ_FACTOR: base64.b64encode(input_stream[76:256]),
                NortekUserConfigDataParticleKey.FILE_COMMENTS: NortekProtocolParameterDict.convert_bytes_to_string(input_stream[256:436]),
                NortekUserConfigDataParticleKey.WAVE_MODE: NortekProtocolParameterDict.convert_bytes_to_bit_field(input_stream[436:438]),
                NortekUserConfigDataParticleKey.PERCENT_WAVE_CELL_POS: NortekProtocolParameterDict.convert_word_to_int(input_stream[438:440]),
                NortekUserConfigDataParticleKey.WAVE_TX_PULSE: NortekProtocolParameterDict.convert_word_to_int(input_stream[440:442]),
                NortekUserConfigDataParticleKey.FIX_WAVE_BLANK_DIST: NortekProtocolParameterDict.convert_word_to_int(input_stream[442:444]),
                NortekUserConfigDataParticleKey.WAVE_CELL_SIZE: NortekProtocolParameterDict.convert_word_to_int(input_stream[444:446]),
                NortekUserConfigDataParticleKey.NUM_DIAG_PER_WAVE: NortekProtocolParameterDict.convert_word_to_int(input_stream[446:448]),
                NortekUserConfigDataParticleKey.NUM_SAMPLE_PER_BURST: NortekProtocolParameterDict.convert_word_to_int(input_stream[452:454]),
                NortekUserConfigDataParticleKey.ANALOG_SCALE_FACTOR: NortekProtocolParameterDict.convert_word_to_int(input_stream[456:458]),
                NortekUserConfigDataParticleKey.CORRELATION_THRS: NortekProtocolParameterDict.convert_word_to_int(input_stream[458:460]),
                NortekUserConfigDataParticleKey.TX_PULSE_LEN_2ND: NortekProtocolParameterDict.convert_word_to_int(input_stream[462:464]),
                NortekUserConfigDataParticleKey.FILTER_CONSTANTS: base64.b64encode(input_stream[494:510]),
                NortekUserConfigDataParticleKey.CHECKSUM: NortekProtocolParameterDict.convert_word_to_int(input_stream[510:512])}

    return parsed


class NortekUserConfigDataParticleKey(BaseEnum):
    """
    User Config particle keys
    """
    TX_LENGTH = 'transmit_pulse_length'
    BLANK_DIST = 'blanking_distance'
    RX_LENGTH = 'receive_length'
    TIME_BETWEEN_PINGS = 'time_between_pings'
    TIME_BETWEEN_BURSTS = 'time_between_bursts'
    NUM_PINGS = 'number_pings'
    AVG_INTERVAL = 'average_interval'
    NUM_BEAMS = 'number_beams'
    PROFILE_TYPE = 'profile_type'
    MODE_TYPE = 'mode_type'
    TCR = 'tcr'
    PCR = 'pcr'
    POWER_TCM1 = 'power_level_tcm1'
    POWER_TCM2 = 'power_level_tcm2'
    SYNC_OUT_POSITION = 'sync_out_position'
    SAMPLE_ON_SYNC = 'sample_on_sync'
    START_ON_SYNC = 'start_on_sync'
    POWER_PCR1 = 'power_level_pcr1'
    POWER_PCR2 = 'power_level_pcr2'
    COMPASS_UPDATE_RATE = 'compass_update_rate'
    COORDINATE_SYSTEM = 'coordinate_system'
    NUM_CELLS = 'number_cells'
    CELL_SIZE = 'cell_size'
    MEASUREMENT_INTERVAL = 'measurement_interval'
    DEPLOYMENT_NAME = 'deployment_name'
    WRAP_MODE = 'wrap_moder'
    DEPLOY_START_TIME = 'deployment_start_time'
    DIAG_INTERVAL = 'diagnostics_interval'
    MODE = 'mode'
    USE_SPEC_SOUND_SPEED = 'use_specified_sound_speed'
    DIAG_MODE_ON = 'diagnostics_mode_enable'
    ANALOG_OUTPUT_ON = 'analog_output_enable'
    OUTPUT_FORMAT = 'output_format_nortek'
    SCALING = 'scaling'
    SERIAL_OUT_ON = 'serial_output_enable'
    STAGE_ON = 'stage_enable'
    ANALOG_POWER_OUTPUT = 'analog_power_output'
    SOUND_SPEED_ADJUST = 'sound_speed_adjust_factor'
    NUM_DIAG_SAMPLES = 'number_diagnostics_samples'
    NUM_BEAMS_PER_CELL = 'number_beams_per_cell'
    NUM_PINGS_DIAG = 'number_pings_diagnostic'
    MODE_TEST = 'mode_test'
    USE_DSP_FILTER = 'use_dsp_filter'
    FILTER_DATA_OUTPUT = 'filter_data_output'
    ANALOG_INPUT_ADDR = 'analog_input_address'
    SW_VER = 'software_version'
    VELOCITY_ADJ_FACTOR = 'velocity_adjustment_factor'
    FILE_COMMENTS = 'file_comments'
    WAVE_MODE = 'wave_mode'
    WAVE_DATA_RATE = 'wave_data_rate'
    WAVE_CELL_POS = 'wave_cell_pos'
    DYNAMIC_POS_TYPE = 'dynamic_position_type'
    PERCENT_WAVE_CELL_POS = 'percent_wave_cell_position'
    WAVE_TX_PULSE = 'wave_transmit_pulse'
    FIX_WAVE_BLANK_DIST = 'fixed_wave_blanking_distance'
    WAVE_CELL_SIZE = 'wave_measurement_cell_size'
    NUM_DIAG_PER_WAVE = 'number_diagnostics_per_wave'
    NUM_SAMPLE_PER_BURST = 'number_samples_per_burst'
    ANALOG_SCALE_FACTOR = 'analog_scale_factor'
    CORRELATION_THRS = 'correlation_threshold'
    TX_PULSE_LEN_2ND = 'transmit_pulse_length_2nd'
    FILTER_CONSTANTS = 'filter_constants'
    CHECKSUM = 'checksum'


class NortekUserConfigDataParticle(DataParticle):
    """
    Routine for parsing head config data into a data particle structure for the Vector sensor. 
    """
    _data_particle_type = NortekDataParticleType.USER_CONFIG

    @log_method
    def _build_parsed_values(self):
        """
        Use the user config data sample format and parse stream into
        values with appropriate tags.
        """
        working_value = user_config_to_dict(self.raw_data)
        for key in working_value.keys():
            if None == working_value[key]:
                raise SampleException("No %s value parsed", key)

        # Fill in the bitfields    
        working_value[NortekUserConfigDataParticleKey.PROFILE_TYPE] = working_value[NortekUserConfigDataParticleKey.TCR][-2]
        working_value[NortekUserConfigDataParticleKey.MODE_TYPE] = working_value[NortekUserConfigDataParticleKey.TCR][-3]
        working_value[NortekUserConfigDataParticleKey.POWER_TCM1] = working_value[NortekUserConfigDataParticleKey.TCR][-6]
        working_value[NortekUserConfigDataParticleKey.POWER_TCM2] = working_value[NortekUserConfigDataParticleKey.TCR][-7]
        working_value[NortekUserConfigDataParticleKey.SYNC_OUT_POSITION] = working_value[NortekUserConfigDataParticleKey.TCR][-8]
        working_value[NortekUserConfigDataParticleKey.SAMPLE_ON_SYNC] = working_value[NortekUserConfigDataParticleKey.TCR][-9]
        working_value[NortekUserConfigDataParticleKey.START_ON_SYNC] = working_value[NortekUserConfigDataParticleKey.TCR][-10]

        working_value[NortekUserConfigDataParticleKey.POWER_PCR1] = working_value[NortekUserConfigDataParticleKey.PCR][-6]
        working_value[NortekUserConfigDataParticleKey.POWER_PCR2] = working_value[NortekUserConfigDataParticleKey.PCR][-7]

        working_value[NortekUserConfigDataParticleKey.USE_SPEC_SOUND_SPEED] = bool(working_value[NortekUserConfigDataParticleKey.MODE][-1])
        working_value[NortekUserConfigDataParticleKey.DIAG_MODE_ON] = bool(working_value[NortekUserConfigDataParticleKey.MODE][-2])
        working_value[NortekUserConfigDataParticleKey.ANALOG_OUTPUT_ON] = bool(working_value[NortekUserConfigDataParticleKey.MODE][-3])
        working_value[NortekUserConfigDataParticleKey.OUTPUT_FORMAT] = working_value[NortekUserConfigDataParticleKey.MODE][-4]
        working_value[NortekUserConfigDataParticleKey.SCALING] = working_value[NortekUserConfigDataParticleKey.MODE][-5]
        working_value[NortekUserConfigDataParticleKey.SERIAL_OUT_ON] = bool(working_value[NortekUserConfigDataParticleKey.MODE][-6])
        working_value[NortekUserConfigDataParticleKey.STAGE_ON] = bool(working_value[NortekUserConfigDataParticleKey.MODE][-8])
        working_value[NortekUserConfigDataParticleKey.ANALOG_POWER_OUTPUT] = bool(working_value[NortekUserConfigDataParticleKey.MODE][-9])

        working_value[NortekUserConfigDataParticleKey.USE_DSP_FILTER] = bool(working_value[NortekUserConfigDataParticleKey.MODE_TEST][-1])
        working_value[NortekUserConfigDataParticleKey.FILTER_DATA_OUTPUT] = working_value[NortekUserConfigDataParticleKey.MODE_TEST][-2]

        working_value[NortekUserConfigDataParticleKey.WAVE_DATA_RATE] = working_value[NortekUserConfigDataParticleKey.WAVE_MODE][-1]
        working_value[NortekUserConfigDataParticleKey.WAVE_CELL_POS] = working_value[NortekUserConfigDataParticleKey.WAVE_MODE][-2]
        working_value[NortekUserConfigDataParticleKey.DYNAMIC_POS_TYPE] = working_value[NortekUserConfigDataParticleKey.WAVE_MODE][-3]

        for key in working_value.keys():
            if None == working_value[key]:
                raise SampleException("No %s value parsed", key)

        # report values
        result = [{DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.TX_LENGTH,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.TX_LENGTH]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.BLANK_DIST,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.BLANK_DIST]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.RX_LENGTH,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.RX_LENGTH]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.TIME_BETWEEN_PINGS,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.TIME_BETWEEN_PINGS]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.TIME_BETWEEN_BURSTS,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.TIME_BETWEEN_BURSTS]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.NUM_PINGS,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.NUM_PINGS]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.AVG_INTERVAL,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.AVG_INTERVAL]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.NUM_BEAMS,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.NUM_BEAMS]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.PROFILE_TYPE,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.PROFILE_TYPE]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.MODE_TYPE,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.MODE_TYPE]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.POWER_TCM1,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.POWER_TCM1]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.POWER_TCM2,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.POWER_TCM2]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.SYNC_OUT_POSITION,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.SYNC_OUT_POSITION]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.SAMPLE_ON_SYNC,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.SAMPLE_ON_SYNC]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.START_ON_SYNC,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.START_ON_SYNC]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.POWER_PCR1,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.POWER_PCR1]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.POWER_PCR2,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.POWER_PCR2]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.COMPASS_UPDATE_RATE,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.COMPASS_UPDATE_RATE]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.COORDINATE_SYSTEM,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.COORDINATE_SYSTEM]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.NUM_CELLS,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.NUM_CELLS]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.CELL_SIZE,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.CELL_SIZE]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.MEASUREMENT_INTERVAL,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.MEASUREMENT_INTERVAL]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.DEPLOYMENT_NAME,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.DEPLOYMENT_NAME]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.WRAP_MODE,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.WRAP_MODE]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.DEPLOY_START_TIME,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.DEPLOY_START_TIME]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.DIAG_INTERVAL,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.DIAG_INTERVAL]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.USE_SPEC_SOUND_SPEED,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.USE_SPEC_SOUND_SPEED]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.DIAG_MODE_ON,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.DIAG_MODE_ON]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.ANALOG_OUTPUT_ON,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.ANALOG_OUTPUT_ON]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.OUTPUT_FORMAT,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.OUTPUT_FORMAT]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.SCALING,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.SCALING]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.SERIAL_OUT_ON,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.SERIAL_OUT_ON]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.STAGE_ON,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.STAGE_ON]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.ANALOG_POWER_OUTPUT,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.ANALOG_POWER_OUTPUT]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.SOUND_SPEED_ADJUST,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.SOUND_SPEED_ADJUST]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.NUM_DIAG_SAMPLES,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.NUM_DIAG_SAMPLES]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.NUM_BEAMS_PER_CELL,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.NUM_BEAMS_PER_CELL]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.NUM_PINGS_DIAG,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.NUM_PINGS_DIAG]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.USE_DSP_FILTER,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.USE_DSP_FILTER]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.FILTER_DATA_OUTPUT,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.FILTER_DATA_OUTPUT]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.ANALOG_INPUT_ADDR,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.ANALOG_INPUT_ADDR]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.SW_VER,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.SW_VER]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.VELOCITY_ADJ_FACTOR,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.VELOCITY_ADJ_FACTOR]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.FILE_COMMENTS,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.FILE_COMMENTS]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.WAVE_DATA_RATE,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.WAVE_DATA_RATE]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.WAVE_CELL_POS,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.WAVE_CELL_POS]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.DYNAMIC_POS_TYPE,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.DYNAMIC_POS_TYPE]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.PERCENT_WAVE_CELL_POS,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.PERCENT_WAVE_CELL_POS]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.WAVE_TX_PULSE,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.WAVE_TX_PULSE]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.FIX_WAVE_BLANK_DIST,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.FIX_WAVE_BLANK_DIST]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.WAVE_CELL_SIZE,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.WAVE_CELL_SIZE]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.NUM_DIAG_PER_WAVE,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.NUM_DIAG_PER_WAVE]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.NUM_SAMPLE_PER_BURST,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.NUM_SAMPLE_PER_BURST]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.ANALOG_SCALE_FACTOR,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.ANALOG_SCALE_FACTOR]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.CORRELATION_THRS,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.CORRELATION_THRS]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.TX_PULSE_LEN_2ND,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.TX_PULSE_LEN_2ND]},
                  {DataParticleKey.VALUE_ID: NortekUserConfigDataParticleKey.FILTER_CONSTANTS,
                   DataParticleKey.VALUE: working_value[NortekUserConfigDataParticleKey.FILTER_CONSTANTS]},
                  ]

        calculated_checksum = NortekProtocolParameterDict.calculate_checksum(self.raw_data)
        if working_value[NortekUserConfigDataParticleKey.CHECKSUM] != calculated_checksum:
            log.warn("Calculated checksum: %s did not match packet checksum: %s",
                     calculated_checksum, working_value[NortekUserConfigDataParticleKey.CHECKSUM])
            self.contents[DataParticleKey.QUALITY_FLAG] = DataParticleValue.CHECKSUM_FAILED

        log.debug('VectorUserConfigDataParticle: particle=%s', result)
        return result


class NortekEngClockDataParticleKey(BaseEnum):
    """
    Particles for the clock data
    """
    DATE_TIME_ARRAY = "date_time_array"
    DATE_TIME_STAMP = "date_time_stamp"


class NortekEngClockDataParticle(DataParticle):
    """
    Routine for parsing clock engineering data into a data particle structure
    for the Vector sensor. 
    """
    _data_particle_type = NortekDataParticleType.CLOCK

    @log_method
    def _build_parsed_values(self):
        """
        Parse sample to create the clock data particle
        """
        match = CLOCK_DATA_REGEX.match(self.raw_data)

        if not match:
            raise SampleException("NortekEngClockDataParticle: No regex match of parsed sample data: [%s]",
                                  self.raw_data)

        date_time_array = [int((match.group(1)).encode("hex")),
                           int((match.group(2)).encode("hex")),
                           int((match.group(3)).encode("hex")),
                           int((match.group(4)).encode("hex")),
                           int((match.group(5)).encode("hex")),
                           int((match.group(6)).encode("hex"))]

        if None == date_time_array:
            raise SampleException("No date/time array value parsed")

        # report values
        result = [{DataParticleKey.VALUE_ID: NortekEngClockDataParticleKey.DATE_TIME_ARRAY,
                   DataParticleKey.VALUE: date_time_array}]

        log.debug('NortekEngClockDataParticle: particle=%s', result)
        return result


class NortekEngBatteryDataParticleKey(BaseEnum):
    """
    Particles for the battery data
    """
    BATTERY_VOLTAGE = "battery_voltage"


class NortekEngBatteryDataParticle(DataParticle):
    """
    Routine for parsing battery engineering data into a data particle.
    """
    _data_particle_type = NortekDataParticleType.BATTERY

    @log_method
    def _build_parsed_values(self):
        """
        Take the battery engineering data sample and parse
        it into values with appropriate tags.
        @throws SampleException If there is a problem with sample creation
        """
        match = BATTERY_DATA_REGEX.match(self.raw_data)

        if not match:
            raise SampleException("NortekEngBatteryDataParticle: No regex match of parsed sample data: [%s]",
                                  self.raw_data)

        # Calculate value
        battery_voltage = NortekProtocolParameterDict.convert_word_to_int(match.group(1))

        if None == battery_voltage:
            raise SampleException("No battery_voltage value parsed")

        # report values
        result = [{DataParticleKey.VALUE_ID: NortekEngBatteryDataParticleKey.BATTERY_VOLTAGE,
                   DataParticleKey.VALUE: battery_voltage}]

        log.debug('NortekEngBatteryDataParticle: particle=%s', result)
        return result


class NortekEngIdDataParticleKey(BaseEnum):
    ID = "identification_string"


class NortekEngIdDataParticle(DataParticle):
    """
    Routine for parsing id engineering data into a data particle
    structure for the Vector sensor. 
    """
    _data_particle_type = NortekDataParticleType.ID_STRING

    @log_method
    def _build_parsed_values(self):
        """
        Take id format and parse stream
        @throws SampleException If there is a problem with sample creation
        """
        match = ID_DATA_REGEX.match(self.raw_data)

        if not match:
            raise SampleException("NortekEngIdDataParticle: No regex match of parsed sample data: [%s]", self.raw_data)

        id_str = NortekProtocolParameterDict.convert_bytes_to_string(match.group(1))

        if None == id_str:
            raise SampleException("No ID value parsed")

        # report values
        result = [{DataParticleKey.VALUE_ID: NortekEngIdDataParticleKey.ID,
                   DataParticleKey.VALUE: id_str}]

        log.debug('NortekEngIdDataParticle: particle=%s', result)
        return result


###############################################################################
# Param dictionary helpers
###############################################################################
class NortekParameterDictVal(RegexParameter):

    @log_method
    def update(self, input, **kwargs):
        """
        Attempt to update a parameter value. If the input string matches the
        value regex, extract and update the dictionary value.
        @param input A string possibly containing the parameter value.
        @retval True if an update was successful, False otherwise.
        """
        init_value = kwargs.get('init_value', False)
        match = self.regex.match(input)
        if match:
            log.debug('NortekDictVal.update(): match=<%s>, init_value=%s', match.group(1).encode('hex'), init_value)
            value = self.f_getval(match)
            if init_value:
                self.description.init_value = value
            else:
                self.value.set_value(value)
            if isinstance(value, int):
                log.debug('NortekParameterDictVal.update(): updated parameter %s=<%d>', self.name, value)
            else:
                log.debug('NortekParameterDictVal.update(): updated parameter %s=\"%s\" <%s>', self.name,
                          value, str(self.value.get_value()).encode('hex'))
            return True
        else:
            log.debug('NortekParameterDictVal.update(): failed to update parameter %s', self.name)
            log.debug('input=%s', input.encode('hex'))
            log.debug('regex=%s', str(self.regex))
            return False


class NortekProtocolParameterDict(ProtocolParameterDict):

    @staticmethod
    def convert_to_raw_value(param_name, initial_value):
        """
        Convert COMMENTS, DEPLOYMENT_NAME, QUAL_CONSTANTS, VELOCITY_ADJ_TABLE,
        and CLOCK_DEPLOY back to their instrument-ready binary representation
        despite them being stored in an ION-friendly not-raw-binary format.
        @retval The raw, instrument-binary value for that name. If the value would
        already be instrument-level coming  out of the param dict, there is
        no change
        """
        if param_name == Parameter.COMMENTS:
            return initial_value.ljust(180, "\x00")
        if param_name == Parameter.DEPLOYMENT_NAME:
            return initial_value.ljust(6, "\x00")
        if param_name == Parameter.QUAL_CONSTANTS:
            return base64.b64decode(initial_value.get_value())
        if param_name == Parameter.VELOCITY_ADJ_TABLE:
            return base64.b64decode(initial_value.get_value())
        if param_name == Parameter.CLOCK_DEPLOY:
            return NortekProtocolParameterDict.convert_datetime_to_words(initial_value.get_value())

        return initial_value

    @log_method
    def get_config(self):
        """
        Retrieve the configuration (all key values not ending in 'Spare').
        """
        config = {}
        for (key, val) in self._param_dict.iteritems():
            log.debug("Getting configuration key [%s] with value: [%s]", key, val.value.value)
            if not key.endswith('Spare'):
                config[key] = val.get_value()
        return config

    @log_method
    def set_from_value(self, name, value):
        """
        Set a parameter value in the dictionary.
        @param name The parameter name.
        @param value The parameter value.
        @raises KeyError if the name is invalid.
        """
        log.debug("NortekProtocolParameterDict.set_from_value(): name=%s, value=%s", name, value)

        if not name in self._param_dict:
            raise InstrumentParameterException('Unable to set parameter %s to %s: parameter %s not an dictionary' % (name, value, name))

        if self._param_dict[name].value.f_format == NortekProtocolParameterDict.word_to_string or \
                self._param_dict[name].value.f_format == NortekProtocolParameterDict.double_word_to_string:
            if not isinstance(value, int):
                raise InstrumentParameterException("Unable to set parameter %s to %s: value not an integer" % (name, value))
        else:
           if not isinstance(value, str):
               raise InstrumentParameterException('Unable to set parameter %s to %s: value not a string' % (name, value))

        if self._param_dict[name].description.visibility == ParameterDictVisibility.READ_ONLY:
            raise ReadOnlyException('Unable to set parameter %s to %s: parameter %s is read only' % (name, value, name))

        self._param_dict[name].value.set_value(value)

    def get_keys(self):
        """
        Return list of device parameters available.  These are a subset of all the parameters
        """
        list = []
        for param in self._param_dict.keys():
            if not param.endswith('Spare'):
                list.append(param)
        log.debug('get_keys: list=%s', list)
        return list

    @staticmethod
    def word_to_string(value):
        """
        Converts a word into a string field
        """
        low_byte = value & 0xff
        high_byte = (value & 0xff00) >> 8
        return chr(low_byte) + chr(high_byte)

    @staticmethod
    def convert_word_to_int(word):
        """
        Converts a word into an integer field
        """
        if len(word) != 2:
            raise SampleException("Invalid number of bytes in word input! Found %s with input %s", len(word))

        low_byte = ord(word[0])
        high_byte = 0x100 * ord(word[1])
        return low_byte + high_byte

    @staticmethod
    def double_word_to_string(value):
        """
        Converts 2 words into a string field
        """
        result = NortekProtocolParameterDict.word_to_string(value & 0xffff)
        result += NortekProtocolParameterDict.word_to_string((value & 0xffff0000) >> 16)
        return result

    @staticmethod
    def convert_double_word_to_int(dword):
        """
        Converts 2 words into an integer field
        """
        if len(dword) != 4:
            raise SampleException("Invalid number of bytes in double word input! Found %s", len(dword))
        low_word = NortekProtocolParameterDict.convert_word_to_int(dword[0:2])
        high_word = NortekProtocolParameterDict.convert_word_to_int(dword[2:4])
        return low_word + (0x10000 * high_word)

    @staticmethod
    def convert_bytes_to_bit_field(bytes):
        """
        Convert bytes to a bit field, reversing bytes in the process.
        ie ['\x05', '\x01'] becomes [0, 0, 0, 1, 0, 1, 0, 1]
        @param bytes an array of string literal bytes.
        @retval an list of 1 or 0 in order 
        """
        byte_list = list(bytes)
        byte_list.reverse()
        result = []
        for byte in byte_list:
            bin_string = bin(ord(byte))[2:].rjust(8, '0')
            result.extend([int(x) for x in list(bin_string)])
        log.trace("Returning a bitfield of %s for input string: [%s]", result, bytes)
        return result

    @staticmethod
    def convert_words_to_datetime(bytes):
        """
        Convert block of 6 words into a date/time structure for the
        instrument family
        @param bytes 6 bytes
        @retval An array of 6 ints corresponding to the date/time structure
        @raise SampleException If the date/time cannot be found
        """
        log.debug("Converting date/time bytes (ord values): %s", map(ord, bytes))
        if len(bytes) != 6:
            raise SampleException("Invalid number of bytes in input! Found %s" % len(bytes))

        list = NortekProtocolParameterDict.convert_to_array(bytes, 1)
        for i in range(0, len(list)):
            list[i] = int(list[i].encode("hex"))

        return list

    @staticmethod
    def convert_datetime_to_words(int_array):
        """
        Convert array if integers into a block of 6 words that could be fed
        back to the instrument as a timestamp. The 6 array probably came from
        convert_words_to_datetime in the first place.
        @param int_array An array of 6 hex values corresponding to a vector
        date/time stamp.
        @retval A string of 6 binary characters
        """
        if len(int_array) != 6:
            raise SampleException("Invalid number of bytes in date/time input! Found %s" % len(int_array))

        list = [chr(int(str(n), 16)) for n in int_array]
        return "".join(list)

    @staticmethod
    def convert_to_array(bytes, item_size):
        """
        Convert the byte stream into a array with each element being
        item_size bytes. ie '\x01\x02\x03\x04' with item_size 2 becomes
        ['\x01\x02', '\x03\x04'] 
        @param item_size the size in bytes to make each element
        @retval An array with elements of the correct size
        @raise SampleException if there are problems unpacking the bytes or
        fitting them all in evenly.
        """
        length = len(bytes)
        if length % item_size != 0:
            raise SampleException("Uneven number of bytes for size %s" % item_size)
        l = list(bytes)
        result = []
        for i in range(0, length, item_size):
            result.append("".join(l[i:i + item_size]))
        return result

    @staticmethod
    def calculate_checksum(input, length=None):
        """
        Calculate the checksum
        """
        calculated_checksum = CHECK_SUM_SEED
        if length is None:
            length = len(input)
        for word_index in range(0, length - 2, 2):
            word_value = NortekProtocolParameterDict.convert_word_to_int(input[word_index:word_index + 2])
            calculated_checksum = (calculated_checksum + word_value) % 0x10000
        return calculated_checksum

    @staticmethod
    def convert_bytes_to_string(bytes_in):
        """
        Convert a list of bytes into a string, remove trailing nulls
        ie. ['\x65', '\x66'] turns into "ef"
        @param bytes_in The byte list to take in
        @retval The string to return
        """
        ba = bytearray(bytes_in)
        return str(ba).split('\x00', 1)[0]

    @staticmethod
    def convert_time(response):
        """
        Converts the timestamp in hex to D:M:YYYY HH:MM:SS
        """
        t = str(response[2].encode('hex'))  # get day
        t += '/' + str(response[5].encode('hex'))  # get month   
        t += '/20' + str(response[4].encode('hex'))  # get year   
        t += ' ' + str(response[3].encode('hex'))  # get hours   
        t += ':' + str(response[0].encode('hex'))  # get minutes   
        t += ':' + str(response[1].encode('hex'))  # get seconds   
        return t


###############################################################################
# Driver
###############################################################################
class NortekInstrumentDriver(SingleConnectionInstrumentDriver):
    """
    Base class for all seabird instrument drivers.
    """
    def __init__(self, evt_callback):
        """
        Driver constructor.
        @param evt_callback Driver process event callback.
        """
        #Construct superclass.
        SingleConnectionInstrumentDriver.__init__(self, evt_callback)

    def _build_protocol(self):
        """
        Construct the driver protocol state machine.
        """
        self._protocol = NortekInstrumentProtocol(InstrumentPrompts, NEWLINE, self._driver_event)

    def get_resource_params(self):
        """
        Return list of device parameters available.
        """
        return Parameter.list()


###############################################################################
# Protocol
###############################################################################
# noinspection PyPep8
class NortekInstrumentProtocol(CommandResponseInstrumentProtocol):
    """
    Instrument protocol class for seabird driver.
    Subclass CommandResponseInstrumentProtoco
    """

    @log_method
    def __init__(self, prompts, newline, driver_event):
        """
        Protocol constructor.
        @param prompts A BaseEnum class containing instrument prompts.
        @param newline The newline.
        @param driver_event Driver process event callback.
        """
        # Construct protocol superclass.
        CommandResponseInstrumentProtocol.__init__(self, prompts, newline, driver_event)

        # Build protocol state machine.
        self._protocol_fsm = InstrumentFSM(ProtocolState,
                                           ProtocolEvent,
                                           ProtocolEvent.ENTER,
                                           ProtocolEvent.EXIT)

        # Add event handlers for protocol state machine.
        self._protocol_fsm.add_handler(ProtocolState.UNKNOWN, ProtocolEvent.ENTER, self._handler_unknown_enter)
        self._protocol_fsm.add_handler(ProtocolState.UNKNOWN, ProtocolEvent.DISCOVER, self._handler_unknown_discover)
        self._protocol_fsm.add_handler(ProtocolState.UNKNOWN, ProtocolEvent.EXIT, self._handler_unknown_exit)

        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.ENTER, self._handler_command_enter)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.EXIT, self._handler_command_exit)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.SET, self._handler_command_set)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.GET, self._handler_get)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.RESET, self._handler_command_execute_reset)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.START_AUTOSAMPLE, self._handler_command_start_autosample)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.ACQUIRE_SAMPLE, self._handler_command_acquire_sample)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.ACQUIRE_STATUS, self._handler_acquire_status)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.START_DIRECT, self._handler_command_start_direct)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.SET_CONFIGURATION, self._handler_command_set_configuration)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.CLOCK_SYNC, self._handler_command_clock_sync)
        #TODO - DO WE WANT SCHEDULED EVENTS TO HAPPEN WHILE IN COMMAND MODE?
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.SCHEDULED_CLOCK_SYNC, self._handler_command_clock_sync)
        self._protocol_fsm.add_handler(ProtocolState.COMMAND, ProtocolEvent.SCHEDULED_ACQUIRE_STATUS, self._handler_acquire_status)

        self._protocol_fsm.add_handler(ProtocolState.AUTOSAMPLE, ProtocolEvent.ENTER, self._handler_autosample_enter)
        self._protocol_fsm.add_handler(ProtocolState.AUTOSAMPLE, ProtocolEvent.EXIT, self._handler_autosample_exit)
        self._protocol_fsm.add_handler(ProtocolState.AUTOSAMPLE, ProtocolEvent.STOP_AUTOSAMPLE, self._handler_autosample_stop_autosample)
        self._protocol_fsm.add_handler(ProtocolState.AUTOSAMPLE, ProtocolEvent.SCHEDULED_CLOCK_SYNC, self._handler_autosample_clock_sync)
        self._protocol_fsm.add_handler(ProtocolState.AUTOSAMPLE, ProtocolEvent.SCHEDULED_ACQUIRE_STATUS, self._handler_acquire_status)

        self._protocol_fsm.add_handler(ProtocolState.DIRECT_ACCESS, ProtocolEvent.ENTER, self._handler_direct_access_enter)
        self._protocol_fsm.add_handler(ProtocolState.DIRECT_ACCESS, ProtocolEvent.EXIT, self._handler_direct_access_exit)
        self._protocol_fsm.add_handler(ProtocolState.DIRECT_ACCESS, ProtocolEvent.STOP_DIRECT, self._handler_direct_access_stop_direct)
        self._protocol_fsm.add_handler(ProtocolState.DIRECT_ACCESS, ProtocolEvent.EXECUTE_DIRECT, self._handler_direct_access_execute_direct)

        # State state machine in UNKNOWN state.
        self._protocol_fsm.start(ProtocolState.UNKNOWN)

        # Add build handlers for device commands.
        self._add_build_handler(InstrumentCmds.CONFIGURE_INSTRUMENT, self._build_set_configuration_command)
        self._add_build_handler(InstrumentCmds.SET_REAL_TIME_CLOCK, self._build_set_real_time_clock_command)

        # Add response handlers for device commands.
        self._add_response_handler(InstrumentCmds.CMD_WHAT_MODE, self._parse_what_mode_response)
        self._add_response_handler(InstrumentCmds.READ_HW_CONFIGURATION, self._parse_read_hw_config)
        self._add_response_handler(InstrumentCmds.READ_HEAD_CONFIGURATION, self._parse_read_head_config)
        self._add_response_handler(InstrumentCmds.READ_USER_CONFIGURATION, self._parse_read_user_config)

        # Construct the parameter dictionary containing device parameters,
        # current parameter values, and set formatting functions.
        self._build_param_dict()
        self._build_cmd_dict()
        self._build_driver_dict()

        self._chunker = StringChunker(NortekInstrumentProtocol.chunker_sieve_function)

    @staticmethod
    @log_method
    def chunker_sieve_function(raw_data, add_structs=[]):
        """
        Detects data sample structures from instrument
        """
        return_list = []
        structs = add_structs + NORTEK_COMMON_SAMPLE_STRUCTS

        for structure_sync, structure_len in structs:

            index = 0
            start = 0

            #while there are still matches....
            while start != -1 :
                start = raw_data.find(structure_sync, index)
                # found a sync pattern
                if start != -1:

                    # only check the CRC if all of the structure has arrived
                    if start+structure_len <= len(raw_data):

                        calculated_checksum = NortekProtocolParameterDict.calculate_checksum(raw_data[start:start+structure_len], structure_len)
                        sent_checksum = NortekProtocolParameterDict.convert_word_to_int(raw_data[start+structure_len-2:start+structure_len])
                        log.debug('chunker_sieve_function: calculated checksum = %s vs sent_checksum = %s', calculated_checksum, sent_checksum)

                        if sent_checksum == calculated_checksum:
                            return_list.append((start, start+structure_len))
                            #slice raw data off
                            log.debug("chunker_sieve_function: found %r", raw_data[start:start+structure_len])

                    index = start+structure_len

         # by this point, all the particles with headers have been parsed from the raw data
        # what's left can be battery voltage and/or identification string
        if len(NORTEK_COMMON_DYNAMIC_SAMPLE_STRUCTS):
            for structure_sync, structure_len in NORTEK_COMMON_DYNAMIC_SAMPLE_STRUCTS:
                start = raw_data.find(structure_sync)
                if start != -1:    # found a "sync" pattern
                    return_list.append((start, start+len(structure_sync)))
                    log.debug("chunker_sieve_function: found %s", raw_data[start:start+len(structure_sync)].encode('hex'))
                    NORTEK_COMMON_DYNAMIC_SAMPLE_STRUCTS.remove([structure_sync, structure_len])

        return return_list

    ########################################################################
    # overridden superclass methods
    ########################################################################
    @log_method
    def _filter_capabilities(self, events):
        """
        Filters capabilities
        """
        events_out = [x for x in events if Capability.has(x)]
        return events_out

    @log_method
    def set_init_params(self, config):
        """
        over-ridden to handle binary block configuration
        Set the initialization parameters to the given values in the protocol
        parameter dictionary. 
        @param config A driver configuration dict that should contain an
        enclosed dict with key DriverConfigKey.PARAMETERS. This should include
        either param_name/value pairs or
           {DriverParameter.ALL: base64-encoded string of raw values as the
           instrument would return them from a get config}. If the desired value
           is false, nothing will happen.
        @raise InstrumentParameterException If the config cannot be set
        """
        log.debug("set_init_params: param_config=%s", config)
        if not isinstance(config, dict):
            raise InstrumentParameterException("Invalid init config format")

        param_config = config.get(DriverConfigKey.PARAMETERS)

        if not param_config:
            return

        if DriverParameter.ALL in param_config:
            binary_config = base64.b64decode(param_config[DriverParameter.ALL])
            # make the configuration string look like it came from instrument to get all the methods to be happy
            binary_config += InstrumentPrompts.Z_ACK
            log.debug("binary_config len=%d, binary_config=%s",
                      len(binary_config), binary_config.encode('hex'))

            if len(binary_config) == USER_CONFIG_LEN+2:
                if self._check_configuration(binary_config, USER_CONFIG_SYNC_BYTES, USER_CONFIG_LEN):
                    self._param_dict.update(binary_config)
                else:
                    raise InstrumentParameterException("bad configuration")
            else:
                raise InstrumentParameterException("configuration not the correct length")
        else:
            for name in param_config.keys():
                self._param_dict.set_init_value(name, param_config[name])

    @log_method
    def _set_params(self, *args, **kwargs):
        """
        Issue commands to the instrument to set various parameters
        Also called when setting parameters during startup and direct access
        """
        params = args[0]

        try:
            self._verify_not_readonly(*args, **kwargs)
            old_config = self._param_dict.get_config()

            response = self._do_cmd_resp(InstrumentCmds.CONFIGURE_INSTRUMENT, expected_prompt=InstrumentPrompts.Z_ACK)

            #TODO
            self._param_dict.update(response)
            log.debug("configure command response: %s", response)

            # Get new param dict config. If it differs from the old config,
            # tell driver superclass to publish a config change event.
            new_config = self._param_dict.get_config()
            log.debug("new_config: %s == old_config: %s", new_config, old_config)
            if not dict_equal(old_config, new_config):
                log.debug("configuration has changed.  Send driver event")
                self._driver_event(DriverAsyncEvent.CONFIG_CHANGE)

        except InstrumentParameterException:
            log.debug("Attempt to set read only parameter(s) (%s)", params)

    def _handler_acquire_status(self):
        """
        Sends commands to receive the status of the instrument. Will put the instrument into command mode if not already
        at that state, to start acquiring status.
        Will put instrument back into command mode if that was the starting state, else stay in
        measuring/autosample mode.
        """

        log.debug("CURRENT STATE: %s", self.get_current_state())
        currentState = self.get_current_state()

        if self.get_current_state() != DriverProtocolState.COMMAND:
            log.debug("Not in command state. Putting driver into command state")
            #enter command mode
            self._connection.send(InstrumentCmds.SOFT_BREAK_FIRST_HALF)
            time.sleep(.1)
            self._do_cmd_resp(InstrumentCmds.SOFT_BREAK_SECOND_HALF)
            time.sleep(.1)
            self._do_cmd_resp(InstrumentCmds.CONFIRMATION, expected_prompt=InstrumentPrompts.Z_ACK)

        #GA - can use this command but need to define a new response handler
        # result = self._do_cmd_resp(InstrumentCmds.GET_ALL_CONFIGURATIONS)

        #BV
         # self._handler_command_read_battery_voltage()
        self._do_cmd_resp(InstrumentCmds.READ_BATTERY_VOLTAGE)
        #
        # #RC
        self._do_cmd_resp(InstrumentCmds.READ_REAL_TIME_CLOCK)

        # #GP
        self._do_cmd_resp(InstrumentCmds.READ_HW_CONFIGURATION)

        #GH
        # self._do_cmd_resp(InstrumentCmds.READ_HEAD_CONFIGURATION)

        #GC
        # self._do_cmd_resp(InstrumentCmds.READ_USER_CONFIGURATION)

        # result_hw = self._handler_command_get_hw_config()

        #II
        # result = self._do_cmd_resp(InstrumentCmds.CMD_WHAT_MODE, expected_prompt=InstrumentPrompts.Z_ACK,
        #                            timeout=TIMEOUT)



         # #enter measuring mode
        # self._do_cmd_resp(InstrumentCmds.START_MEASUREMENT_WITHOUT_RECORDER, expected_prompt=InstrumentPrompts.Z_ACK,
        #                   timeout=TIMEOUT)
        #
        # #I
        # self._do_cmd_resp(InstrumentCmds.SAMPLE_WHAT_MODE, expected_prompt=InstrumentPrompts.Z_ACK,
        #                                timeout=TIMEOUT)
        # #A
        # self._do_cmd_resp(InstrumentCmds.SAMPLE_AVG_TIME, expected_prompt=InstrumentPrompts.Z_ACK,
        #                                timeout=TIMEOUT)
        # #M
        # self._do_cmd_resp(InstrumentCmds.SAMPLE_INTERVAL_TIME, expected_prompt=InstrumentPrompts.Z_ACK,
        #                                timeout=TIMEOUT)

        #put instrument back into previous state
        if currentState == DriverProtocolState.COMMAND:
            #enter command mode
            self._connection.send(InstrumentCmds.SOFT_BREAK_FIRST_HALF)
            time.sleep(.1)
            self._do_cmd_resp(InstrumentCmds.SOFT_BREAK_SECOND_HALF)
            time.sleep(.1)
            self._do_cmd_resp(InstrumentCmds.CONFIRMATION, expected_prompt=InstrumentPrompts.Z_ACK)

    ########################################################################
    # Unknown handlers.
    ########################################################################
    @log_method
    def _handler_unknown_enter(self, *args, **kwargs):
        """
        Enter unknown state.
        """
        # Tell driver superclass to send a state change event.
        # Superclass will query the state.
        self._driver_event(DriverAsyncEvent.STATE_CHANGE)

    @log_method
    def _handler_unknown_discover(self, *args, **kwargs):
        """
        Discover current state of instrument; can be COMMAND or AUTOSAMPLE.
        @retval (next_state, result)
        """
        # try to discover the device mode using timeout if passed.
        timeout = kwargs.get('timeout', TIMEOUT)
        prompt = self._get_mode(timeout)

        if prompt == InstrumentPrompts.COMMAND_MODE:
            next_state = ProtocolState.COMMAND
            result = ResourceAgentState.IDLE
        elif prompt == InstrumentPrompts.CONFIRMATION:
            next_state = ProtocolState.AUTOSAMPLE
            result = ResourceAgentState.STREAMING
        elif prompt == InstrumentPrompts.Z_ACK:
            log.debug('_handler_unknown_discover: promptbuf=%s (%s)', self._promptbuf, self._promptbuf.encode("hex"))

            if InstrumentModes.COMMAND in self._promptbuf:
                next_state = ProtocolState.COMMAND
                result = ResourceAgentState.IDLE
            elif InstrumentModes.MEASUREMENT in self._promptbuf or InstrumentModes.CONFIRMATION in self._promptbuf:
                next_state = ProtocolState.AUTOSAMPLE
                result = ResourceAgentState.STREAMING
            else:
                raise InstrumentStateException('Unknown state.')
        else:
            raise InstrumentStateException('Unknown state.')

        log.debug('_handler_unknown_discover: state=%s', next_state)
        return next_state, result

    @log_method
    def _handler_unknown_exit(self, *args, **kwargs):
        """
        Exiting Unknown state
        """
        pass

    ########################################################################
    # Command handlers.
    ########################################################################
    @log_method
    def _handler_command_enter(self, *args, **kwargs):
        """
        Enter command state.
        @throws InstrumentTimeoutException if the device cannot be woken.
        @throws InstrumentProtocolException if the update commands and not recognized.
        """
        # Command device to update parameters and send a config change event.
        self._update_params()

        # Tell driver superclass to send a state change event.
        # Superclass will query the state.
        self._driver_event(DriverAsyncEvent.STATE_CHANGE)

    @log_method
    def _handler_command_exit(self, *args, **kwargs):
        """
        Exit command state.
        """
        pass

    @log_method
    def _handler_command_acquire_sample(self, *args, **kwargs):
        """
        Command the instrument to acquire sample data. Instrument will enter Power Down mode when finished
        """
        result = self._do_cmd_resp(InstrumentCmds.ACQUIRE_DATA, expected_prompt=InstrumentPrompts.Z_ACK, timeout=TIMEOUT)
        return None, (None, result)

    @log_method
    def _handler_command_execute_reset(self, *args, **kwargs):
        """

        """
        result = self._do_cmd_resp(InstrumentCmds.POWER_DOWN, expected_prompt=InstrumentPrompts.Z_ACK, timeout=TIMEOUT)
        return None, (None, result)

    def _handler_command_set_engineering_param(self, *args, **kwargs):
        try:
            params_to_set = args[0]
        except IndexError:
            raise InstrumentParameterException('Set command requires a parameter dict.')
        else:
            if not isinstance(params_to_set, dict):
                raise InstrumentParameterException('Set parameters not a dict.')

        parameters = copy.copy(self._param_dict)    # get copy of parameters to modify

         # For each key, value in the params_to_set list set the value in parameters copy.
        name = None
        value = None
        try:
            for (name, value) in params_to_set.iteritems():
                log.debug('_handler_command_set: setting %s to %s', name, value)
                parameters.set_from_value(name, value)
        except Exception as ex:
            raise InstrumentParameterException('Unable to set parameter %s to %s: %s' % (name, value, ex))

    @log_method
    def _handler_command_set(self, *args, **kwargs):
        """
        Perform a set command.
        @param args[0] parameter : value dict.
        @retval (next_state, result) tuple, (None, None).
        @throws InstrumentParameterException if missing set parameters, if set parameters not ALL and
        not a dict, or if parameter can't be properly formatted.
        @throws InstrumentTimeoutException if device cannot be woken for set command.
        @throws InstrumentProtocolException if set command could not be built or misunderstood.
        """

        # Retrieve required parameter from args.
        # Raise exception if no parameter provided, or not a dict.
        try:
            params_to_set = args[0]
        except IndexError:
            raise InstrumentParameterException('Set command requires a parameter dict.')
        else:
            if not isinstance(params_to_set, dict):
                raise InstrumentParameterException('Set parameters not a dict.')

        parameters = copy.copy(self._param_dict)    # get copy of parameters to modify

        # For each key, value in the params_to_set list set the value in parameters copy.
        name = None
        value = None
        try:
            for (name, value) in params_to_set.iteritems():
                log.debug('_handler_command_set: setting %s to %s', name, value)
                parameters.set_from_value(name, value)
        except Exception as ex:
            raise InstrumentParameterException('Unable to set parameter %s to %s: %s' % (name, value, ex))

        output = self._create_set_output(parameters)

        log.debug('_handler_command_set: writing instrument configuration to instrument')

        self._connection.send(InstrumentCmds.CONFIGURE_INSTRUMENT)
        self._connection.send(output)

        # Clear the prompt buffer.
        self._promptbuf = ''
        self._get_response(timeout=TIMEOUT, expected_prompt=InstrumentPrompts.Z_ACK)
        self._update_params()

        return None, None

    @log_method
    def _handler_get(self, *args, **kwargs):
        """
        Get device parameters from the parameter dict.
        @param args[0] list of parameters to retrieve, or DriverParameter.ALL.
        @throws InstrumentParameterException if missing or invalid parameter.
        """
        # Retrieve the required parameter, raise if not present.
        try:
            params = args[0]

        except IndexError:
            raise InstrumentParameterException('Get command requires a parameter list or tuple.')
        # If all params requested, retrieve config.
        if (params == DriverParameter.ALL) or (params == [DriverParameter.ALL]):
            result = self._param_dict.get_config()

        # If not all params, confirm a list or tuple of params to retrieve.
        # Raise if not a list or tuple.
        # Retrieve each key in the list, raise if any are invalid.
        else:
            if not isinstance(params, (list, tuple)):
                raise InstrumentParameterException('Get argument not a list or tuple.')
            result = {}
            for key in params:
                try:
                    val = self._param_dict.get(key)
                    result[key] = val

                except KeyError:
                    raise InstrumentParameterException(('%s is not a valid parameter.' % key))

        return None, result

    @log_method
    def _handler_command_start_autosample(self, *args, **kwargs):
        """
        Switch into autosample mode, syncing the clock first
        @retval (next_state, result) tuple, (AUTOSAMPLE, None) if successful.
        @throws InstrumentTimeoutException if device cannot be woken for command.
        @throws InstrumentProtocolException if command could not be built or misunderstood.
        """
        self._protocol_fsm.on_event(ProtocolEvent.CLOCK_SYNC)

        result = self._do_cmd_resp(InstrumentCmds.START_MEASUREMENT_WITHOUT_RECORDER, expected_prompt=InstrumentPrompts.Z_ACK,
                          timeout=TIMEOUT)

        return ProtocolState.AUTOSAMPLE, (ResourceAgentState.STREAMING, result)

    @log_method
    def _handler_command_start_direct(self):
        """
        Start Direct Access
        """
        return ProtocolState.DIRECT_ACCESS, ResourceAgentState.DIRECT_ACCESS

    @log_method
    def _handler_command_set_configuration(self, *args, **kwargs):
        """
        """
        # Issue set user configuration command.
        result = self._do_cmd_resp(InstrumentCmds.CONFIGURE_INSTRUMENT,
                                   expected_prompt=InstrumentPrompts.Z_ACK, *args, **kwargs)

        return None, (None, result)

    @log_method
    def _clock_sync(self, *args, **kwargs):
        """
        The mechanics of synchronizing a clock
        @throws InstrumentTimeoutException if device cannot be woken for command.
        @throws InstrumentProtocolException if command could not be built or misunderstood.
        """
        str_time = get_timestamp_delayed("%M %S %d %H %y %m")
        byte_time = ''
        for v in str_time.split():
            byte_time += chr(int('0x'+v, base=16))
        values = str_time.split()
        log.info("_clock_sync: time set to %s:m %s:s %s:d %s:h %s:y %s:M (%s)",
                 values[0], values[1], values[2], values[3], values[4], values[5],
                 byte_time.encode('hex'))
        result = self._do_cmd_resp(InstrumentCmds.SET_REAL_TIME_CLOCK, byte_time, **kwargs)
        return result

    @log_method
    def _handler_command_clock_sync(self, *args, **kwargs):
        """
        sync clock close to a second edge 
        @retval (next_state, result) tuple, (None, None) if successful.
        @throws InstrumentTimeoutException if device cannot be woken for command.
        @throws InstrumentProtocolException if command could not be built or misunderstood.
        """
        result = self._clock_sync()
        return None, (None, result)

    ########################################################################
    # Autosample handlers.
    ########################################################################
    @log_method
    def _handler_autosample_clock_sync(self, *args, **kwargs):
        """
        While in autosample, sync a clock close to a second edge 
        @retval (next_state, result) tuple, (None, None) if successful.
        @throws InstrumentTimeoutException if device cannot be woken for command.
        @throws InstrumentProtocolException if command could not be built or misunderstood.
        """
        #put driver in command state
        self._connection.send(InstrumentCmds.SOFT_BREAK_FIRST_HALF)
        time.sleep(.1)
        self._do_cmd_resp(InstrumentCmds.SOFT_BREAK_SECOND_HALF, expected_prompt=InstrumentPrompts.CONFIRMATION,
                          *args, **kwargs)
        # Issue the confirmation command.
        self._do_cmd_resp(InstrumentCmds.CONFIRMATION, expected_prompt=InstrumentPrompts.Z_ACK, *args, **kwargs)

        #sync clock
        self._clock_sync()

        #put driver back into measurement state
        self._connection.send(InstrumentCmds.SOFT_BREAK_FIRST_HALF)
        time.sleep(.1)
        result = self._do_cmd_resp(InstrumentCmds.SOFT_BREAK_SECOND_HALF, *args, **kwargs)

        return None, (None, result)

    @log_method
    def _handler_autosample_enter(self, *args, **kwargs):
        """
        Enter autosample state.
        """
        # Tell driver superclass to send a state change event.
        # Superclass will query the state.
        self._driver_event(DriverAsyncEvent.STATE_CHANGE)

        log.debug("Configuring the scheduler to sync clock %s", self._param_dict.get(EngineeringParameter.CLOCK_SYNC_INTERVAL))
        if self._param_dict.get(EngineeringParameter.CLOCK_SYNC_INTERVAL) != '00:00:00':
            self.start_scheduled_job(EngineeringParameter.CLOCK_SYNC_INTERVAL, ScheduledJob.CLOCK_SYNC, ProtocolEvent.CLOCK_SYNC)

        log.debug("Configuring the scheduler to acquire status %s", self._param_dict.get(EngineeringParameter.ACQUIRE_STATUS_INTERVAL))
        if self._param_dict.get(EngineeringParameter.ACQUIRE_STATUS_INTERVAL) != '00:00:00':
            self.start_scheduled_job(EngineeringParameter.ACQUIRE_STATUS_INTERVAL, ScheduledJob.ACQUIRE_STATUS, ProtocolEvent.ACQUIRE_STATUS)


    @log_method
    def _handler_autosample_exit(self, *args, **kwargs):
        """
        Exit autosample state.
        """
        self.stop_scheduled_job(ScheduledJob.ACQUIRE_STATUS)
        self.stop_scheduled_job(ScheduledJob.CLOCK_SYNC)

        pass

    @log_method
    def _handler_autosample_stop_autosample(self, *args, **kwargs):
        """
        Stop autosample and switch back to command mode.
        @retval (next_state, result) tuple, (SBE37ProtocolState.COMMAND,
        None) if successful.
        @throws InstrumentTimeoutException if device cannot be woken for command.
        @throws InstrumentProtocolException if command misunderstood or
        incorrect prompt received.
        """
        # send soft break
        self._connection.send(InstrumentCmds.SOFT_BREAK_FIRST_HALF)
        time.sleep(.1)
        self._do_cmd_resp(InstrumentCmds.SOFT_BREAK_SECOND_HALF, expected_prompt=InstrumentPrompts.CONFIRMATION, *args, **kwargs)

        # Issue the confirmation command.
        time.sleep(.1)
        result = self._do_cmd_resp(InstrumentCmds.CONFIRMATION, expected_prompt=InstrumentPrompts.Z_ACK, *args, **kwargs)

        return ProtocolState.COMMAND, (ResourceAgentState.COMMAND, result)

    def stop_scheduled_job(self, schedule_job):
        """
        Remove the scheduled job
        """
        log.debug("Attempting to remove the scheduler")
        if self._scheduler is not None:
            try:
                self._remove_scheduler(schedule_job)
                log.debug("successfully removed scheduler")
            except KeyError:
                log.debug("_remove_scheduler could not find %s", schedule_job)

    def start_scheduled_job(self, param, schedule_job, protocol_event):
        """
        Add a scheduled job
        """
        interval = self._param_dict.get(param).split(':')
        hours = interval[0]
        minutes = interval[1]
        seconds = interval[2]
        log.debug("Setting scheduled interval to: %s %s %s", hours, minutes, seconds)

        config = {DriverConfigKey.SCHEDULER: {
            schedule_job: {
                DriverSchedulerConfigKey.TRIGGER: {
                    DriverSchedulerConfigKey.TRIGGER_TYPE: TriggerType.INTERVAL,
                    DriverSchedulerConfigKey.HOURS: int(hours),
                    DriverSchedulerConfigKey.MINUTES: int(minutes),
                    DriverSchedulerConfigKey.SECONDS: int(seconds)
                }
            }
        }
        }
        self.set_init_params(config)
        self._add_scheduler_event(schedule_job, protocol_event)

    ########################################################################
    # Direct access handlers.
    ########################################################################
    @log_method
    def _handler_direct_access_enter(self, *args, **kwargs):
        """
        Enter direct access state.
        """
        # Tell driver superclass to send a state change event.
        # Superclass will query the state.
        self._driver_event(DriverAsyncEvent.STATE_CHANGE)
        self._sent_cmds = []

    @log_method
    def _handler_direct_access_exit(self, *args, **kwargs):
        """
        Exit direct access state.
        """
        pass

    @log_method
    def _handler_direct_access_execute_direct(self, data):
        """
        Execute Direct Access command(s)
        """
        self._do_cmd_direct(data)

        # add sent command to list for 'echo' filtering in callback
        self._sent_cmds.append(data)

        return None, (None, None)

    @log_method
    def _handler_direct_access_stop_direct(self):
        """
        Stop Direct Access, and put the driver into a healthy state by reverting itself back to the previous
        state before starting Direct Access.
        @throw InstrumentProtocolException on invalid command
        """
        #TODO - IMPLEMENT

        #discover the state to go to next
        next_state, next_agent_state = self._handler_unknown_discover()
        if next_state == DriverProtocolState.COMMAND:
            next_agent_state = ResourceAgentState.COMMAND

        # if next_state == DriverProtocolState.AUTOSAMPLE:
        #     #go into command mode
        #     self._do_cmd_no_resp(InstrumentCommand.Interrupt_instrument)
        #
        # da_params = self.get_direct_access_params()
        # log.debug("DA params to reset: %s", da_params)
        # for param in da_params:
        #
        #     log.debug('Trying to reset param %s', param)
        #
        #     old_val = self._param_dict.get(param)
        #     new_val = self._param_dict.get_default_value(param)
        #
        #     log.debug('Comparing %s == %s', old_val, new_val)
        #
        #
        #     self._param_dict.set_value(param, new_val)
        #     self._do_cmd_resp(InstrumentCommand.SET, param, new_val, response_regex=MNU_REGEX_MATCHER)
        #
        # if next_state == DriverProtocolState.AUTOSAMPLE:
        #     #go into autosample mode
        #     self._do_cmd_no_resp(InstrumentCommand.Run_settings)
        #
        # log.debug("Next_state = %s, Next_agent_state = %s", next_state, next_agent_state)
        return next_state, (next_agent_state, None)

    ########################################################################
    # Common handlers.
    ########################################################################
    @log_method
    def _dump_config(self, input):
        # dump config block
        dump = ''
        for byte_index in range(0, len(input)):
            if byte_index % 0x10 == 0:
                if byte_index != 0:
                    dump += '\n'   # no linefeed on first line
                dump += '{:03x}  '.format(byte_index)
            dump += '{:02x} '.format(ord(input[byte_index]))
        return dump

    @log_method
    def _check_configuration(self, input, sync, length):
        log.debug('_check_configuration: config=%s', self._dump_config(input))
        #print self._dump_config(input)
        if len(input) != length + 2:
            log.debug('_check_configuration: wrong length, expected length %d != %d', length + 2, len(input))
            return False

        # check for ACK bytes
        if input[length:length+2] != InstrumentPrompts.Z_ACK:
            log.debug('_check_configuration: ACK bytes in error %s != %s', input[length:length+2].encode('hex'),
                      InstrumentPrompts.Z_ACK.encode('hex'))
            return False

        # check the sync bytes
        if input[0:4] != sync:
            log.debug('_check_configuration: sync bytes in error %s != %s', input[0:4], sync)
            return False

        # check checksum
        calculated_checksum = NortekProtocolParameterDict.calculate_checksum(input, length)
        log.debug('_check_configuration: user c_c = %s', calculated_checksum)
        sent_checksum = NortekProtocolParameterDict.convert_word_to_int(input[length - 2:length])
        if sent_checksum != calculated_checksum:
            log.debug('_check_configuration: user checksum in error %s != %s',
                      calculated_checksum, sent_checksum)
            return False

        return True

    @log_method
    def _update_params(self, *args, **kwargs):
        """
        Update the parameter dictionary. Issue the upload command. The response
        needs to be iterated through a line at a time and values saved.
        @throws InstrumentTimeoutException if device cannot be timely woken.
        @throws InstrumentProtocolException if ds/dc misunderstood.
        """
        if self.get_current_state() != ProtocolState.COMMAND:
            raise InstrumentStateException('Can not perform update of parameters when not in command state')
        # Get old param dict config.
        old_config = self._param_dict.get_config()

        # get user_configuration params from the instrument
        # Grab time for timeout.
        starttime = time.time()
        timeout = 6

        while True:
            # Clear the prompt buffer.
            self._promptbuf = ''

            log.debug('Sending get_user_configuration command to the instrument.')
            # Send get_user_cofig command to attempt to get user configuration.
            self._connection.send(InstrumentCmds.READ_USER_CONFIGURATION)
            for i in range(20):   # loop for 2 seconds waiting for response to complete
                if len(self._promptbuf) == USER_CONFIG_LEN+2:
                    if self._check_configuration(self._promptbuf, USER_CONFIG_SYNC_BYTES, USER_CONFIG_LEN):
                        self._param_dict.update(self._promptbuf)
                        new_config = self._param_dict.get_config()
                        if new_config != old_config:
                            self._driver_event(DriverAsyncEvent.CONFIG_CHANGE)
                        return
                    break
                time.sleep(.1)
            log.debug('_update_params: get_user_configuration command response length %d not right, %s',
                      len(self._promptbuf), self._promptbuf.encode("hex"))

            if time.time() > starttime + timeout:
                raise InstrumentTimeoutException()

            continue

    @log_method
    def _get_mode(self, timeout, delay=1):
        """
        search for
        prompt strings at other than just the end of the line.
        @param timeout The timeout to wake the device.
        @param delay The time to wait between consecutive wakeups.
        @throw InstrumentTimeoutException if the device could not be woken.
        """
        # Clear the prompt buffer.

        self._promptbuf = ''

        # Grab time for timeout.
        starttime = time.time()

        log.debug("_get_mode: timeout = %d", timeout)

        while True:
            log.debug('Sending what_mode command to get a response from the instrument.')
            # Send what_mode command to attempt to get a response.
            self._connection.send(InstrumentCmds.CMD_WHAT_MODE)
            time.sleep(delay)

            for item in self._prompts.list():
                if item in self._promptbuf:
                    if item != InstrumentPrompts.Z_NACK:
                        log.debug('get_mode got prompt: %s', repr(item))
                        return item

            if time.time() > starttime + timeout:
                raise InstrumentTimeoutException()

    @log_method
    def _create_set_output(self, parameters):
        # load buffer with sync byte (A5), ID byte (0), and size word (# of words in little-endian form)
        # 'user' configuration is 512 bytes, 256 words long, so size is 0x100
        output = '\xa5\x00\x00\x01'
        for name in Parameter:
            log.debug('_create_set_output: adding %s to list', name)
            if name == Parameter.COMMENTS:
                output += parameters.format(name).ljust(180, "\x00")
            elif name == Parameter.DEPLOYMENT_NAME:
                output += parameters.format(name).ljust(6, "\x00")
            elif name == Parameter.QUAL_CONSTANTS:
                output += base64.b64decode(parameters.format(name))
            elif name == Parameter.VELOCITY_ADJ_TABLE:
                output += base64.b64decode(parameters.format(name))
            elif name == Parameter.CLOCK_DEPLOY:
                output += NortekProtocolParameterDict.convert_datetime_to_words(parameters.format(name))
            else:
                output += parameters.format(name)
        log.debug("Created set output: %s with length: %s", output, len(output))

        checksum = CHECK_SUM_SEED
        for word_index in range(0, len(output), 2):
            word_value = NortekProtocolParameterDict.convert_word_to_int(output[word_index:word_index+2])
            checksum = (checksum + word_value) % 0x10000
        log.debug('_create_set_output: user checksum = %s', checksum)

        output += NortekProtocolParameterDict.word_to_string(checksum)
        self._dump_config(output)

        return output

    @log_method
    def _build_set_configuration_command(self, cmd, *args, **kwargs):
        user_configuration = kwargs.get('user_configuration', None)
        if not user_configuration:
            raise InstrumentParameterException('set_configuration command missing user_configuration parameter.')
        if not isinstance(user_configuration, str):
            raise InstrumentParameterException('set_configuration command requires a string user_configuration parameter.')
        user_configuration = base64.b64decode(user_configuration)
        self._dump_config(user_configuration)

        cmd_line = cmd + user_configuration
        return cmd_line

    @log_method
    def _build_set_real_time_clock_command(self, cmd, time, **kwargs):
        return cmd + time

    @log_method
    def _parse_read_clock_response(self, response, prompt):
        """ Parse the response from the instrument for a read clock command.

        @param response The response string from the instrument
        @param prompt The prompt received from the instrument
        @retval return The time as a string
        @raise InstrumentProtocolException When a bad response is encountered
        """
        # packed BCD format, so convert binary to hex to get value
        # should be the 6 byte response ending with two ACKs
        if len(response) != 8:
            log.warn("_parse_read_clock_response: Bad read clock response from instrument (%s)", response.encode('hex'))
            raise InstrumentProtocolException("Invalid read clock response. (%s)" % response.encode('hex'))
        log.debug("_parse_read_clock_response: response=%s", response.encode('hex'))

        # Workaround for not so unique data particle chunking
        NORTEK_COMMON_DYNAMIC_SAMPLE_STRUCTS.append([response, ID_LEN])

        ret_val = NortekProtocolParameterDict.convert_time(response)
        return ret_val

    @log_method
    def _parse_what_mode_response(self, response, prompt):
        """ Parse the response from the instrument for a 'what mode' command.

        @param response The response string from the instrument
        @param prompt The prompt received from the instrument
        @retval return The time as a string
        @raise InstrumentProtocolException When a bad response is encountered
        """
        if len(response) != 4:
            log.warn("_parse_what_mode_response: Bad what mode response from instrument (%s)", response.encode('hex'))
            raise InstrumentProtocolException("Invalid what mode response. (%s)" % response.encode('hex'))
        log.debug("_parse_what_mode_response: response=%s", response.encode('hex'))
        return NortekProtocolParameterDict.convert_word_to_int(response[0:2])

    @log_method
    def _parse_read_hw_config(self, response, prompt):
        """ Parse the response from the instrument for a read hw config command.

        @param response The response string from the instrument
        @param prompt The prompt received from the instrument
        @retval return The hardware configuration parse into a dict. Names
        include SerialNo (string), Config (int), Frequency(int),
        PICversion (int), HWrevision (int), RecSize (int), Status (int), and
        FWversion (binary)
        @raise InstrumentProtocolException When a bad response is encountered
        """
        if not self._check_configuration(self._promptbuf, HW_CONFIG_SYNC_BYTES, HW_CONFIG_LEN):
            log.warn("_parse_read_hw_config: Bad read hw response from instrument (%s)", response.encode('hex'))
            raise InstrumentProtocolException("Invalid read hw response. (%s)" % response.encode('hex'))
        log.debug("_parse_read_hw_config: response=%s", response.encode('hex'))

        return hw_config_to_dict(response)

    @log_method
    def _parse_read_head_config(self, response, prompt):
        """ Parse the response from the instrument for a read head command.

        @param response The response string from the instrument
        @param prompt The prompt received from the instrument
        @retval return The head configuration parsed into a dict. Names include
        Config (int), Frequency (int), Type (int), SerialNo (string)
        System (binary), NBeams (int)
        @raise InstrumentProtocolException When a bad response is encountered
        """
        if not self._check_configuration(self._promptbuf, HEAD_CONFIG_SYNC_BYTES, HEAD_CONFIG_LEN):
            log.warn("_parse_read_head_config: Bad read head response from instrument (%s)", response.encode('hex'))
            raise InstrumentProtocolException("Invalid read head response. (%s)" % response.encode('hex'))
        log.debug("_parse_read_head_config: response=%s", response.encode('hex'))

        return head_config_to_dict(response)

    @log_method
    def _parse_read_user_config(self, response, prompt):
        """ Parse the response from the instrument for a read user command.

        @param response The response string from the instrument
        @param prompt The prompt received from the instrument
        @retval return The user configuration parsed into a dict. Names include:

        @raise InstrumentProtocolException When a bad response is encountered
        """
        if not self._check_configuration(self._promptbuf, USER_CONFIG_SYNC_BYTES, USER_CONFIG_LEN):
            log.warn("_parse_read_user_config: Bad read user response from instrument (%s)", response.encode('hex'))
            raise InstrumentProtocolException("Invalid read user response. (%s)" % response.encode('hex'))
        log.debug("_parse_read_user_config: response=%s", response.encode('hex'))

        #return response
        return user_config_to_dict(response)

    @log_method
    def _send_wakeup(self):
        """
        Send a newline to attempt to wake the sbe26plus device.
        """
        self._connection.send(InstrumentCmds.SOFT_BREAK_FIRST_HALF)
        time.sleep(.1)
        self._connection.send(InstrumentCmds.SOFT_BREAK_SECOND_HALF)

    @log_method
    def _build_driver_dict(self):
        """
        Build a driver dictionary structure, load the strings for the metadata
        from a file if present.
        """
        self._driver_dict = DriverDict()
        self._driver_dict.add(DriverDictKey.VENDOR_SW_COMPATIBLE, True)

    @log_method
    def _build_cmd_dict(self):
        """
        Build a command dictionary structure, load the strings for the metadata
        from a file if present.
        """
        #TODO
        self._cmd_dict = ProtocolCommandDict()
        # self._cmd_dict.add(Capability.SET)
        # self._cmd_dict.add(Capability.GET)
        self._cmd_dict.add(Capability.ACQUIRE_SAMPLE)
        # self._cmd_dict.add(Capability.START_AUTOSAMPLE)
        # self._cmd_dict.add(Capability.STOP_AUTOSAMPLE)
        self._cmd_dict.add(Capability.CLOCK_SYNC)
        self._cmd_dict.add(Capability.SET_CONFIGURATION)
        self._cmd_dict.add(Capability.RESET)
        # self._cmd_dict.add(Capability.READ_CLOCK)
        # self._cmd_dict.add(Capability.READ_MODE)
        # self._cmd_dict.add(Capability.POWER_DOWN)
        # self._cmd_dict.add(Capability.READ_BATTERY_VOLTAGE)
        # self._cmd_dict.add(Capability.READ_ID)
        # self._cmd_dict.add(Capability.GET_HW_CONFIGURATION)
        # self._cmd_dict.add(Capability.GET_HEAD_CONFIGURATION)
        # self._cmd_dict.add(Capability.READ_USER_CONFIGURATION)

    @log_method
    def _build_param_dict(self):
        """
        Populate the parameter dictionary with parameters.
        For each parameter key, add match string, match lambda function,
        and value formatting function for set commands.
        """
        # The parameter dictionary.
        self._param_dict = NortekProtocolParameterDict()

        self._param_dict.add_parameter(
                                    NortekParameterDictVal(Parameter.TRANSMIT_PULSE_LENGTH,
                                    r'^.{%s}(.{2}).*' % str(4),
                                    lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                    NortekProtocolParameterDict.word_to_string,
                                    regex_flags=re.DOTALL,
                                    type=ParameterDictType.INT,
                                    expiration=None,
                                    visibility=ParameterDictVisibility.READ_WRITE,
                                    display_name="transmit pulse length",
                                    default_value=2,
                                    startup_param=True,
                                    direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.BLANKING_DISTANCE,
                                   r'^.{%s}(.{2}).*' % str(6),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_WRITE,
                                   display_name="blanking distance",
                                   default_value=16,
                                   startup_param=True,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.RECEIVE_LENGTH,
                                   r'^.{%s}(.{2}).*' % str(8),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_WRITE,
                                   display_name="receive length",
                                   default_value=7,
                                   startup_param=True,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.TIME_BETWEEN_PINGS,
                                   r'^.{%s}(.{2}).*' % str(10),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_WRITE,
                                   display_name="time between pings",
                                   default_value=None,
                                   startup_param=True,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.TIME_BETWEEN_BURST_SEQUENCES,
                                   r'^.{%s}(.{2}).*' % str(12),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="time between burst sequences",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.NUMBER_PINGS,
                                   r'^.{%s}(.{2}).*' % str(14),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="number pings",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.AVG_INTERVAL,
                                   r'^.{%s}(.{2}).*' % str(16),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   init_value=60,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_WRITE,
                                   display_name="avg interval",
                                   default_value=32,
                                   startup_param=True,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.USER_NUMBER_BEAMS,
                                   r'^.{%s}(.{2}).*' % str(18),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="user number beams",
                                   default_value=3,
                                   startup_param=False,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.TIMING_CONTROL_REGISTER,
                                   r'^.{%s}(.{2}).*' % str(20),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="timing control register",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.POWER_CONTROL_REGISTER,
                                   r'^.{%s}(.{2}).*' % str(22),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="power control register",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.A1_1_SPARE,
                                   r'^.{%s}(.{2}).*' % str(24),
                                   lambda match: match.group(1),
                                   lambda string: string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="a1 1 spare",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.B0_1_SPARE,
                                   r'^.{%s}(.{2}).*' % str(26),
                                   lambda match: match.group(1),
                                   lambda string: string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="b0 1 spare",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.B1_1_SPARE,
                                   r'^.{%s}(.{2}).*' % str(28),
                                   lambda match: match.group(1),
                                   lambda string: string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="b1 1 spare",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.COMPASS_UPDATE_RATE,
                                   r'^.{%s}(.{2}).*' % str(30),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   init_value=2,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="compass update rate",
                                   default_value=1,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.COORDINATE_SYSTEM,
                                   r'^.{%s}(.{2}).*' % str(32),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   init_value=1,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_WRITE,
                                   display_name="coordinate system",
                                   default_value=0,
                                   startup_param=True,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.NUMBER_BINS,
                                   r'^.{%s}(.{2}).*' % str(34),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="number bins",
                                   default_value=1,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.BIN_LENGTH,
                                   r'^.{%s}(.{2}).*' % str(36),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="bin length",
                                   default_value=7,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.MEASUREMENT_INTERVAL,
                                   r'^.{%s}(.{2}).*' % str(38),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   init_value=3600,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="measurement interval",
                                   default_value=3600,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.DEPLOYMENT_NAME,
                                   r'^.{%s}(.{6}).*' % str(40),
                                   lambda match: NortekProtocolParameterDict.convert_bytes_to_string(match.group(1)),
                                   lambda string: string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="deployment name",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.WRAP_MODE,
                                   r'^.{%s}(.{2}).*' % str(46),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="wrap mode",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.CLOCK_DEPLOY,
                                   r'^.{%s}(.{6}).*' % str(48),
                                   lambda match: NortekProtocolParameterDict.convert_words_to_datetime(match.group(1)),
                                   lambda string: string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="clock deploy",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.DIAGNOSTIC_INTERVAL,
                                   r'^.{%s}(.{4}).*' % str(54),
                                   lambda match: NortekProtocolParameterDict.convert_double_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.double_word_to_string,
                                   init_value=43200,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="diagnostic interval",
                                   default_value=10800,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.MODE,
                                   r'^.{%s}(.{2}).*' % str(58),
                                   lambda match: NortekProtocolParameterDict.convert_double_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="mode",
                                   default_value=96,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.ADJUSTMENT_SOUND_SPEED,
                                   r'^.{%s}(.{2}).*' % str(60),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_WRITE,
                                   display_name="adjustment sound speed",
                                   default_value=1525,
                                   startup_param=True,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.NUMBER_SAMPLES_DIAGNOSTIC,
                                   r'^.{%s}(.{2}).*' % str(62),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   init_value=20,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="number samples diagnostic",
                                   default_value=1,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.NUMBER_BEAMS_CELL_DIAGNOSTIC,
                                   r'^.{%s}(.{2}).*' % str(64),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="number beams cell diagnostic",
                                   default_value=1,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.NUMBER_PINGS_DIAGNOSTIC,
                                   r'^.{%s}(.{2}).*' % str(66),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="number pings diagnostic",
                                   default_value=1,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.MODE_TEST,
                                   r'^.{%s}(.{2}).*' % str(68),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="mode test",
                                   default_value=None,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.ANALOG_INPUT_ADDR,
                                   r'^.{%s}(.{2}).*' % str(70),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="analog input addr",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.SW_VERSION,
                                   r'^.{%s}(.{2}).*' % str(72),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="sw version",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.USER_1_SPARE,
                                   r'^.{%s}(.{2}).*' % str(74),
                                   lambda match: match.group(1),
                                   lambda string : string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="user 1 spare",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.VELOCITY_ADJ_TABLE,
                                   r'^.{%s}(.{180}).*' % str(76),
                                   lambda match: base64.b64encode(match.group(1)),
                                   #lambda match: match.group(1),
                                   #lambda string : base64.b64encode(string),
                                   lambda string : string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="velocity adj table",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.COMMENTS,
                                   r'^.{%s}(.{180}).*' % str(256),
                                   lambda match: NortekProtocolParameterDict.convert_bytes_to_string(match.group(1)),
                                   #lambda match: match.group(1),
                                   lambda string : string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="comments",
                                   default_value=None,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.WAVE_MEASUREMENT_MODE,
                                   r'^.{%s}(.{2}).*' % str(436),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="wave measurement mode",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.DYN_PERCENTAGE_POSITION,
                                   r'^.{%s}(.{2}).*' % str(438),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="dyn percentage position",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.WAVE_TRANSMIT_PULSE,
                                   r'^.{%s}(.{2}).*' % str(440),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="wave transmit pulse",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.WAVE_BLANKING_DISTANCE,
                                   r'^.{%s}(.{2}).*' % str(442),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="wave blanking distance",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.WAVE_CELL_SIZE,
                                   r'^.{%s}(.{2}).*' % str(444),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="wave cell size",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.NUMBER_DIAG_SAMPLES,
                                   r'^.{%s}(.{2}).*' % str(446),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="number diag samples",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.A1_2_SPARE,
                                   r'^.{%s}(.{2}).*' % str(448),
                                   lambda match: match.group(1),
                                   lambda string : string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="a1 2 spare",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.B0_2_SPARE,
                                   r'^.{%s}(.{2}).*' % str(450),
                                   lambda match: match.group(1),
                                   lambda string : string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="b0 2 spare",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.NUMBER_SAMPLES_PER_BURST,
                                   r'^.{%s}(.{2}).*' % str(452),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="number samples per burst",
                                   default_value=0,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.USER_2_SPARE,
                                   r'^.{%s}(.{2}).*' % str(454),
                                   lambda match: match.group(1),
                                   lambda string : string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="user 2 spare",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.ANALOG_OUTPUT_SCALE,
                                   r'^.{%s}(.{2}).*' % str(456),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="analog output scale",
                                   default_value=None,
                                   startup_param=True,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.CORRELATION_THRESHOLD,
                                   r'^.{%s}(.{2}).*' % str(458),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_WRITE,
                                   display_name="correlation threshold",
                                   default_value=0,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.USER_3_SPARE,
                                    r'^.{%s}(.{2}).*' % str(460),
                                    lambda match: match.group(1),
                                    lambda string : string,
                                    visibility=ParameterDictVisibility.READ_ONLY,
                                    regex_flags=re.DOTALL,
                                    type=ParameterDictType.STRING,
                                    expiration=None,
                                    display_name="spare",
                                    default_value=0,
                                    startup_param=False,
                                    direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.TRANSMIT_PULSE_LENGTH_SECOND_LAG,
                                   r'^.{%s}(.{2}).*' % str(462),
                                   lambda match: NortekProtocolParameterDict.convert_word_to_int(match.group(1)),
                                   NortekProtocolParameterDict.word_to_string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.INT,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="transmit pulse length second lag",
                                   default_value=2,
                                   startup_param=True,
                                   direct_access=True))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.USER_4_SPARE,
                                   r'^.{%s}(.{30}).*' % str(464),
                                   lambda match: match.group(1),
                                   lambda string: string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="user 4 spare",
                                   default_value=None,
                                   startup_param=False,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(Parameter.QUAL_CONSTANTS,
                                   r'^.{%s}(.{16}).*' % str(494),
                                   #lambda match: match.group(1),
                                   lambda match: base64.b64encode(match.group(1)),
                                   lambda string: string,
                                   regex_flags=re.DOTALL,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.READ_ONLY,
                                   display_name="qual constants",
                                   default_value=None,
                                   startup_param=True,
                                   direct_access=True))
        ############################################################################
        # ENGINEERING PARAMETERS
        ###########################################################################
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(EngineeringParameter.CLOCK_SYNC_INTERVAL,
                                   RUN_CLOCK_SYNC_REGEX,
                                   lambda match: match.group(1),
                                   str,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.IMMUTABLE,
                                   display_name="clock sync interval",
                                   default_value='00:00:00',
                                   startup_param=True,
                                   direct_access=False))
        self._param_dict.add_parameter(
                                   NortekParameterDictVal(EngineeringParameter.ACQUIRE_STATUS_INTERVAL,
                                   RUN_CLOCK_SYNC_REGEX,
                                   lambda match: match.group(1),
                                   str,
                                   type=ParameterDictType.STRING,
                                   expiration=None,
                                   visibility=ParameterDictVisibility.IMMUTABLE,
                                   display_name="acquire status interval",
                                   default_value='00:00:00',
                                   startup_param=True,
                                   direct_access=False))

        #set the values of the dictionary using set_default
        for param in self._param_dict.get_keys():
            self._param_dict.set_value(param, self._param_dict.get_default_value(param))
