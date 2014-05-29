"""
@package mi.instrument.teledyne.workhorse.adcp.driver
@file marine-integrations/mi/instrument/teledyne/workhorse/ADCP/test/test_driver.py
@author Sung Ahn
@brief Test Driver for the VADCP
Release notes:

"""

__author__ = 'Sung Ahn'
__license__ = 'Apache 2.0'

import unittest
import datetime as dt
from nose.plugins.attrib import attr
from mock import Mock
from mi.core.instrument.chunker import StringChunker

from mi.core.log import get_logger; log = get_logger()

from mi.instrument.teledyne.workhorse.test.test_driver import WorkhorseDriverUnitTest
from mi.instrument.teledyne.workhorse.test.test_driver import WorkhorseDriverIntegrationTest
from mi.instrument.teledyne.workhorse.test.test_driver import WorkhorseDriverQualificationTest
from mi.instrument.teledyne.workhorse.test.test_driver import WorkhorseDriverPublicationTest
from mi.instrument.teledyne.workhorse.test.test_driver import DataParticleType
from mi.idk.unit_test import InstrumentDriverTestCase

from mi.instrument.teledyne.workhorse.test.test_data import RSN_SAMPLE_RAW_DATA
from mi.instrument.teledyne.workhorse.test.test_data import RSN_CALIBRATION_RAW_DATA
from mi.instrument.teledyne.workhorse.test.test_data import RSN_PS0_RAW_DATA

from mi.idk.unit_test import DriverTestMixin

from mi.idk.unit_test import ParameterTestConfigKey
from mi.idk.unit_test import DriverStartupConfigKey
from mi.instrument.teledyne.workhorse.vadcp.driver import Parameter
from mi.instrument.teledyne.workhorse.adcp.driver import Prompt
from mi.instrument.teledyne.workhorse.adcp.driver import ProtocolEvent
from mi.instrument.teledyne.workhorse.driver import NEWLINE
from mi.instrument.teledyne.workhorse.adcp.driver import ScheduledJob
from mi.instrument.teledyne.workhorse.adcp.driver import Capability
from mi.instrument.teledyne.workhorse.adcp.driver import InstrumentCmds

from mi.instrument.teledyne.workhorse.driver import ADCP_PD0_PARSED_KEY
from mi.instrument.teledyne.workhorse.driver import ADCP_SYSTEM_CONFIGURATION_KEY
from mi.instrument.teledyne.workhorse.driver import ADCP_COMPASS_CALIBRATION_KEY

from mi.instrument.teledyne.workhorse.adcp.driver import InstrumentDriver
from mi.instrument.teledyne.workhorse.adcp.driver import Protocol

from mi.instrument.teledyne.workhorse.adcp.driver import ProtocolState

from mi.idk.comm_config import ConfigTypes
from ion.agents.port.port_agent_process import PortAgentProcess, PortAgentProcessType
from mi.idk.unit_test import InstrumentDriverTestCase, LOCALHOST, ParameterTestConfigKey

from mi.idk.unit_test import InstrumentDriverUnitTestCase
from mi.idk.unit_test import InstrumentDriverIntegrationTestCase
from mi.idk.unit_test import InstrumentDriverQualificationTestCase

from mi.instrument.teledyne.driver import TeledyneProtocolState
from mi.instrument.teledyne.driver import TeledyneProtocolEvent

from mi.instrument.teledyne.driver import TeledyneParameter2
from mi.instrument.teledyne.driver import TeledyneParameter

from mi.core.exceptions import InstrumentCommandException
from mi.core.common import BaseEnum

###
#   Driver parameters for tests
###

InstrumentDriverTestCase.initialize(
    driver_module='mi.instrument.teledyne.workhorse.vadcp.driver',
    driver_class="InstrumentDriver",
    instrument_agent_resource_id = 'HTWZMW',
    instrument_agent_preload_id = 'IA7',
    instrument_agent_name = 'teledyne_workhorse_monitor VADCP',
    instrument_agent_packet_config = DataParticleType(),

    driver_startup_config = {
        DriverStartupConfigKey.PARAMETERS: {
            Parameter.SERIAL_FLOW_CONTROL: '11110',
            Parameter.BANNER: False,
            Parameter.INSTRUMENT_ID: 0,
            Parameter.SLEEP_ENABLE: 0,
            Parameter.SAVE_NVRAM_TO_RECORDER: True,
            Parameter.POLLED_MODE: False,
            Parameter.XMIT_POWER: 255,
            Parameter.SPEED_OF_SOUND: 1485,
            Parameter.PITCH: 0,
            Parameter.ROLL: 0,
            Parameter.SALINITY: 35,
            Parameter.COORDINATE_TRANSFORMATION: '00111',
            Parameter.TIME_PER_ENSEMBLE: '00:00:00.00',
            Parameter.TIME_PER_PING: '00:01.00',
            Parameter.FALSE_TARGET_THRESHOLD: '050,001',
            Parameter.BANDWIDTH_CONTROL: 0,
            Parameter.CORRELATION_THRESHOLD: 64,
            Parameter.SERIAL_OUT_FW_SWITCHES: '111100000',
            Parameter.ERROR_VELOCITY_THRESHOLD: 2000,
            Parameter.BLANK_AFTER_TRANSMIT: 704,
            Parameter.CLIP_DATA_PAST_BOTTOM: 0,
            Parameter.RECEIVER_GAIN_SELECT: 1,
            Parameter.NUMBER_OF_DEPTH_CELLS: 100,
            Parameter.PINGS_PER_ENSEMBLE: 1,
            Parameter.DEPTH_CELL_SIZE: 800,
            Parameter.TRANSMIT_LENGTH: 0,
            Parameter.PING_WEIGHT: 0,
            Parameter.AMBIGUITY_VELOCITY: 175,
            Parameter.LATENCY_TRIGGER: 0,
            Parameter.HEADING_ALIGNMENT: '+00000',
            Parameter.HEADING_BIAS: '+00000',
            Parameter.TRANSDUCER_DEPTH: 8000,
            Parameter.DATA_STREAM_SELECTION: 0,
            Parameter.ENSEMBLE_PER_BURST: 0,
            Parameter.SAMPLE_AMBIENT_SOUND: 0,
            Parameter.BUFFERED_OUTPUT_PERIOD: '00:00:00',

            Parameter.SYNC_PING_ENSEMBLE: '001',
            Parameter.RDS3_MODE_SEL: 1,
            Parameter.SYNCH_DELAY: 100,

            Parameter.CLOCK_SYNCH_INTERVAL: '00:00:00',
            Parameter.GET_STATUS_INTERVAL: '00:00:00',
        },
        DriverStartupConfigKey.SCHEDULER: {
            ScheduledJob.GET_CALIBRATION: {},
            ScheduledJob.GET_CONFIGURATION: {},
            ScheduledJob.CLOCK_SYNC: {}
        }
    }
)

class TeledynePrompt(BaseEnum):
    """
    Device i/o prompts..
    """
    COMMAND = '\r\n>\r\n>'
    ERR = 'ERR:'

###################################################################

###
#   Driver constant definitions
###

###############################################################################
#                           DATA PARTICLE TEST MIXIN                          #
#     Defines a set of assert methods used for data particle verification     #
#                                                                             #
#  In python mixin classes are classes designed such that they wouldn't be    #
#  able to stand on their own, but are inherited by other classes generally   #
#  using multiple inheritance.                                                #
#                                                                             #
# This class defines a configuration structure for testing and common assert  #
# methods for validating data particles.
###############################################################################

class ADCPTMixin(DriverTestMixin):
    '''
    Mixin class used for storing data particle constance
    and common data assertion methods.
    '''
    # Create some short names for the parameter test config
    TYPE      = ParameterTestConfigKey.TYPE
    READONLY  = ParameterTestConfigKey.READONLY
    STARTUP   = ParameterTestConfigKey.STARTUP
    DA        = ParameterTestConfigKey.DIRECT_ACCESS
    VALUE     = ParameterTestConfigKey.VALUE
    REQUIRED  = ParameterTestConfigKey.REQUIRED
    DEFAULT   = ParameterTestConfigKey.DEFAULT
    STATES    = ParameterTestConfigKey.STATES 

    ###
    # Parameter and Type Definitions
    ###
    _driver_parameters = {
        Parameter.SERIAL_DATA_OUT: {TYPE: str, READONLY: True, DA: True, STARTUP: True, DEFAULT: '000 000 000', VALUE:'000 000 000'},
        Parameter.SERIAL_FLOW_CONTROL: {TYPE: str, READONLY: True, DA: True, STARTUP: True, DEFAULT: '11110', VALUE: '11110'},
        Parameter.SAVE_NVRAM_TO_RECORDER: {TYPE: bool, READONLY: True, DA: True, STARTUP: True, DEFAULT: True, VALUE: True},
        Parameter.TIME: {TYPE: str, READONLY: False, DA: False, STARTUP: False, DEFAULT: False},
        Parameter.SERIAL_OUT_FW_SWITCHES: {TYPE: str, READONLY: True, DA: True, STARTUP: True, DEFAULT: '111100000', VALUE: '111100000'},
        Parameter.BANNER: {TYPE: bool, READONLY: True, DA: True, STARTUP: True, DEFAULT: False, VALUE: False},
        Parameter.INSTRUMENT_ID: {TYPE: int, READONLY: True, DA: True, STARTUP: True, DEFAULT: 0, VALUE: 0},
        Parameter.SLEEP_ENABLE: {TYPE: int, READONLY: True, DA: True, STARTUP: True, DEFAULT: 0, VALUE: 0},
        Parameter.POLLED_MODE: {TYPE: bool, READONLY: True, DA: True, STARTUP: True, DEFAULT: False, VALUE: False},
        Parameter.XMIT_POWER: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 255, VALUE: 255},
        Parameter.SPEED_OF_SOUND: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 1485, VALUE: 1485},
        Parameter.PITCH: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 0, VALUE: 0},
        Parameter.ROLL: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 0, VALUE: 0},
        Parameter.SALINITY: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 35, VALUE: 35},
        Parameter.COORDINATE_TRANSFORMATION: {TYPE: str, READONLY: True, DA: True, STARTUP: True, DEFAULT: '00111', VALUE: '00111'},
        Parameter.SENSOR_SOURCE: {TYPE: str, READONLY: False, DA: True, STARTUP: True, DEFAULT: "1111101", VALUE: "1111101"},
        Parameter.TIME_PER_ENSEMBLE: {TYPE: str, READONLY: False, DA: True, STARTUP: True, DEFAULT: False, VALUE: '00:00:00.00'},
        Parameter.TIME_OF_FIRST_PING: {TYPE: str, READONLY: True, DA: False, STARTUP: False, DEFAULT: False}, # STARTUP: True, VALUE: '****/**/**,**:**:**'
        Parameter.TIME_PER_PING: {TYPE: str, READONLY: False, DA: True, STARTUP: True, DEFAULT: '00:01.00', VALUE: '00:01.00'},
        Parameter.FALSE_TARGET_THRESHOLD: {TYPE: str, READONLY: False, DA: True, STARTUP: True, DEFAULT: '050,001', VALUE: '050,001'},
        Parameter.BANDWIDTH_CONTROL: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: False, VALUE: 0},
        Parameter.CORRELATION_THRESHOLD: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 64, VALUE: 64},
        Parameter.ERROR_VELOCITY_THRESHOLD: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 2000, VALUE: 2000},
        Parameter.BLANK_AFTER_TRANSMIT: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 704, VALUE: 704},
        Parameter.CLIP_DATA_PAST_BOTTOM: {TYPE: bool, READONLY: False, DA: True, STARTUP: True, DEFAULT: False, VALUE: 0},
        Parameter.RECEIVER_GAIN_SELECT: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 1, VALUE: 1},
        Parameter.NUMBER_OF_DEPTH_CELLS: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 100, VALUE: 100},
        Parameter.PINGS_PER_ENSEMBLE: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 1, VALUE: 1},
        Parameter.DEPTH_CELL_SIZE: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 800, VALUE: 800},
        Parameter.TRANSMIT_LENGTH: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: False, VALUE: 0},
        Parameter.PING_WEIGHT: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: False, VALUE: 0},
        Parameter.AMBIGUITY_VELOCITY: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 175, VALUE: 175},

        Parameter.LATENCY_TRIGGER: {TYPE: int, READONLY: True, DA: True, STARTUP: True, DEFAULT: 0, VALUE: 0},
        Parameter.HEADING_ALIGNMENT: {TYPE: str, READONLY: True, DA: True, STARTUP: True, DEFAULT: '+00000', VALUE:'+00000'},
        Parameter.HEADING_BIAS: {TYPE: str, READONLY: True, DA: True, STARTUP: True, DEFAULT: '+00000', VALUE:'+00000'},
        Parameter.TRANSDUCER_DEPTH: {TYPE: int, READONLY: False, DA: True, STARTUP: True, DEFAULT: 8000, VALUE:8000},
        Parameter.DATA_STREAM_SELECTION: {TYPE: int, READONLY: True, DA: True, STARTUP: True, DEFAULT: 0, VALUE: 0},
        Parameter.ENSEMBLE_PER_BURST: {TYPE: int, READONLY: True, DA: True, STARTUP: True, DEFAULT: 0, VALUE: 0},
        Parameter.BUFFERED_OUTPUT_PERIOD: {TYPE: str, READONLY: True, DA: True, STARTUP: True, DEFAULT: '00:00:00', VALUE:'00:00:00'},
        Parameter.SAMPLE_AMBIENT_SOUND: {TYPE: int, READONLY: True, DA: True, STARTUP: True, DEFAULT: 0, VALUE:0},

        Parameter.SYNC_PING_ENSEMBLE: {TYPE: str, READONLY: True, DA: True, STARTUP: True, DEFAULT: '001', VALUE: '001'},
        Parameter.RDS3_MODE_SEL: {TYPE: int, READONLY: True, DA: True, STARTUP: True, DEFAULT: 1, VALUE: 1},
        Parameter.SYNCH_DELAY: {TYPE: int, READONLY: True, DA: True, STARTUP: True, DEFAULT: 100, VALUE: 100},

        Parameter.CLOCK_SYNCH_INTERVAL: {TYPE: str, READONLY: False, DA: False, STARTUP: True, DEFAULT: '00:00:00', VALUE: '00:00:00'},
        Parameter.GET_STATUS_INTERVAL: {TYPE: str, READONLY: False, DA: False, STARTUP: True, DEFAULT: '00:00:00', VALUE: '00:00:00'}
    }

    _driver_capabilities = {
        # capabilities defined in the IOS
        Capability.START_AUTOSAMPLE: { STATES: [ProtocolState.COMMAND, ProtocolState.AUTOSAMPLE]},
        Capability.STOP_AUTOSAMPLE: { STATES: [ProtocolState.COMMAND, ProtocolState.AUTOSAMPLE]},
        Capability.CLOCK_SYNC: { STATES: [ProtocolState.COMMAND]},
        Capability.GET_CALIBRATION: { STATES: [ProtocolState.COMMAND]},
        Capability.GET_CONFIGURATION: { STATES: [ProtocolState.COMMAND]},
        Capability.SAVE_SETUP_TO_RAM: { STATES: [ProtocolState.COMMAND]},
        Capability.GET_ERROR_STATUS_WORD: { STATES: [ProtocolState.COMMAND]},
        Capability.CLEAR_ERROR_STATUS_WORD: { STATES: [ProtocolState.COMMAND]},
        Capability.GET_FAULT_LOG: { STATES: [ProtocolState.COMMAND]},
        Capability.CLEAR_FAULT_LOG: { STATES: [ProtocolState.COMMAND]},
        Capability.RUN_TEST_200: { STATES: [ProtocolState.COMMAND]},
        Capability.FACTORY_SETS: { STATES: [ProtocolState.COMMAND]},
        Capability.USER_SETS: { STATES: [ProtocolState.COMMAND]},
        Capability.ACQUIRE_STATUS: { STATES: [ProtocolState.COMMAND]},
        Capability.START_DIRECT: { STATES: [ProtocolState.COMMAND]},
        Capability.STOP_DIRECT: { STATES: [ProtocolState.DIRECT_ACCESS]},
    }

    EF_CHAR = '\xef'
    _calibration_data_parameters = {
        ADCP_COMPASS_CALIBRATION_KEY.FLUXGATE_CALIBRATION_TIMESTAMP: {'type': float, 'value': 1347639932.0 },
        ADCP_COMPASS_CALIBRATION_KEY.S_INVERSE_BX: {'type': list, 'value': [0.39218, 0.3966, -0.031681, 0.0064332] },
        ADCP_COMPASS_CALIBRATION_KEY.S_INVERSE_BY: {'type': list, 'value': [-0.02432, -0.010376, -0.0022428, -0.60628] },
        ADCP_COMPASS_CALIBRATION_KEY.S_INVERSE_BZ: {'type': list, 'value': [0.22453, -0.21972, -0.2799, -0.0024339] },
        ADCP_COMPASS_CALIBRATION_KEY.S_INVERSE_ERR: {'type': list, 'value': [0.46514, -0.40455, 0.69083, -0.014291] },
        ADCP_COMPASS_CALIBRATION_KEY.COIL_OFFSET: {'type': list, 'value': [34233.0, 34449.0, 34389.0, 34698.0] },
        ADCP_COMPASS_CALIBRATION_KEY.ELECTRICAL_NULL: {'type': float, 'value': 34285.0 },
        ADCP_COMPASS_CALIBRATION_KEY.TILT_CALIBRATION_TIMESTAMP: {'type': float, 'value': 1347639285.0 },
        ADCP_COMPASS_CALIBRATION_KEY.CALIBRATION_TEMP: {'type': float, 'value': 24.4 },
        ADCP_COMPASS_CALIBRATION_KEY.ROLL_UP_DOWN: {'type': list, 'value': [7.4612e-07, -3.1727e-05, -3.0054e-07, 3.219e-05] },
        ADCP_COMPASS_CALIBRATION_KEY.PITCH_UP_DOWN: {'type': list, 'value': [-3.1639e-05, -6.3505e-07, -3.1965e-05, -1.4881e-07] },
        ADCP_COMPASS_CALIBRATION_KEY.OFFSET_UP_DOWN: {'type': list, 'value': [32808.0, 32568.0, 32279.0, 33047.0] },
        ADCP_COMPASS_CALIBRATION_KEY.TILT_NULL: {'type': float, 'value': 33500.0 }
    }

    _system_configuration_data_parameters = {
        ADCP_SYSTEM_CONFIGURATION_KEY.SERIAL_NUMBER: {'type': unicode, 'value': "18444" },
        ADCP_SYSTEM_CONFIGURATION_KEY.TRANSDUCER_FREQUENCY: {'type': int, 'value': 76800 }, 
        ADCP_SYSTEM_CONFIGURATION_KEY.CONFIGURATION: {'type': unicode, 'value': "4 BEAM, JANUS" },
        ADCP_SYSTEM_CONFIGURATION_KEY.MATCH_LAYER: {'type': unicode, 'value': "10" },
        ADCP_SYSTEM_CONFIGURATION_KEY.BEAM_ANGLE: {'type': int, 'value': 20 },
        ADCP_SYSTEM_CONFIGURATION_KEY.BEAM_PATTERN: {'type': unicode, 'value': "CONVEX" },
        ADCP_SYSTEM_CONFIGURATION_KEY.ORIENTATION: {'type': unicode, 'value': "UP" },
        ADCP_SYSTEM_CONFIGURATION_KEY.SENSORS: {'type': unicode, 'value': "HEADING  TILT 1  TILT 2  DEPTH  TEMPERATURE  PRESSURE" },
        ADCP_SYSTEM_CONFIGURATION_KEY.PRESSURE_COEFF_c3: {'type': float, 'value': -1.927850E-11 },
        ADCP_SYSTEM_CONFIGURATION_KEY.PRESSURE_COEFF_c2: {'type': float, 'value': +1.281892E-06 },
        ADCP_SYSTEM_CONFIGURATION_KEY.PRESSURE_COEFF_c1: {'type': float, 'value': +1.375793E+00 },
        ADCP_SYSTEM_CONFIGURATION_KEY.PRESSURE_COEFF_OFFSET: {'type': float, 'value': 13.38634 },
        ADCP_SYSTEM_CONFIGURATION_KEY.TEMPERATURE_SENSOR_OFFSET: {'type': float, 'value': -0.01 },
        ADCP_SYSTEM_CONFIGURATION_KEY.CPU_FIRMWARE: {'type': unicode, 'value': "50.40 [0]" },
        ADCP_SYSTEM_CONFIGURATION_KEY.BOOT_CODE_REQUIRED: {'type': unicode, 'value': "1.16" }, 
        ADCP_SYSTEM_CONFIGURATION_KEY.BOOT_CODE_ACTUAL: {'type': unicode, 'value': "1.16" }, 
        ADCP_SYSTEM_CONFIGURATION_KEY.DEMOD_1_VERSION: {'type': unicode, 'value': "ad48" },
        ADCP_SYSTEM_CONFIGURATION_KEY.DEMOD_1_TYPE: {'type': unicode, 'value': "1f" },
        ADCP_SYSTEM_CONFIGURATION_KEY.DEMOD_2_VERSION: {'type': unicode, 'value': "ad48" },
        ADCP_SYSTEM_CONFIGURATION_KEY.DEMOD_2_TYPE: {'type': unicode, 'value': "1f" }, 
        ADCP_SYSTEM_CONFIGURATION_KEY.POWER_TIMING_VERSION: {'type': unicode, 'value': "85d3" }, 
        ADCP_SYSTEM_CONFIGURATION_KEY.POWER_TIMING_TYPE: {'type': unicode, 'value': "7" }, 
        ADCP_SYSTEM_CONFIGURATION_KEY.BOARD_SERIAL_NUMBERS: {'type': unicode, 'value': u"72  00 00 06 FE BC D8  09 HPA727-3009-00B \n" + \
                                                                                    "81  00 00 06 F5 CD 9E  09 REC727-1004-06A\n" + \
                                                                                    "A5  00 00 06 FF 1C 79  09 HPI727-3007-00A\n" + \
                                                                                    "82  00 00 06 FF 23 E5  09 CPU727-2011-00E\n" + \
                                                                                    "07  00 00 06 F6 05 15  09 TUN727-1005-06A\n" + \
                                                                                    "DB  00 00 06 F5 CB 5D  09 DSP727-2001-06H" }
    }

    _pd0_parameters_base = {
        ADCP_PD0_PARSED_KEY.HEADER_ID: {'type': int, 'value': 127 },
        ADCP_PD0_PARSED_KEY.DATA_SOURCE_ID: {'type': int, 'value': 127 },
        ADCP_PD0_PARSED_KEY.NUM_BYTES: {'type': int, 'value': 26632 },
        ADCP_PD0_PARSED_KEY.NUM_DATA_TYPES: {'type': int, 'value': 6 },
        ADCP_PD0_PARSED_KEY.OFFSET_DATA_TYPES: {'type': list, 'value': [18, 77, 142, 944, 1346, 1748, 2150] },
        ADCP_PD0_PARSED_KEY.FIXED_LEADER_ID: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.FIRMWARE_VERSION: {'type': int, 'value': 50 },
        ADCP_PD0_PARSED_KEY.FIRMWARE_REVISION: {'type': int, 'value': 40 },
        ADCP_PD0_PARSED_KEY.SYSCONFIG_FREQUENCY: {'type': int, 'value': 150 },
        ADCP_PD0_PARSED_KEY.SYSCONFIG_BEAM_PATTERN: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.SYSCONFIG_SENSOR_CONFIG: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.SYSCONFIG_HEAD_ATTACHED: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.SYSCONFIG_VERTICAL_ORIENTATION: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.DATA_FLAG: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.LAG_LENGTH: {'type': int, 'value': 53 },
        ADCP_PD0_PARSED_KEY.NUM_BEAMS: {'type': int, 'value': 4 },
        ADCP_PD0_PARSED_KEY.NUM_CELLS: {'type': int, 'value': 100 },
        ADCP_PD0_PARSED_KEY.PINGS_PER_ENSEMBLE: {'type': int, 'value': 256 },
        ADCP_PD0_PARSED_KEY.DEPTH_CELL_LENGTH: {'type': int, 'value': 32780 },
        ADCP_PD0_PARSED_KEY.BLANK_AFTER_TRANSMIT: {'type': int, 'value': 49154 },
        ADCP_PD0_PARSED_KEY.SIGNAL_PROCESSING_MODE: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.LOW_CORR_THRESHOLD: {'type': int, 'value': 64 },
        ADCP_PD0_PARSED_KEY.NUM_CODE_REPETITIONS: {'type': int, 'value': 17 },
        ADCP_PD0_PARSED_KEY.PERCENT_GOOD_MIN: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.ERROR_VEL_THRESHOLD: {'type': int, 'value': 53255 },
        ADCP_PD0_PARSED_KEY.TIME_PER_PING_MINUTES: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.TIME_PER_PING_SECONDS: {'type': float, 'value': 1.0 },
        ADCP_PD0_PARSED_KEY.COORD_TRANSFORM_TYPE: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.COORD_TRANSFORM_TILTS: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.COORD_TRANSFORM_BEAMS: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.COORD_TRANSFORM_MAPPING: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.HEADING_ALIGNMENT: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.HEADING_BIAS: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.SENSOR_SOURCE_SPEED: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.SENSOR_SOURCE_DEPTH: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.SENSOR_SOURCE_HEADING: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.SENSOR_SOURCE_PITCH: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.SENSOR_SOURCE_ROLL: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.SENSOR_SOURCE_CONDUCTIVITY: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.SENSOR_SOURCE_TEMPERATURE: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.SENSOR_AVAILABLE_DEPTH: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.SENSOR_AVAILABLE_HEADING: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.SENSOR_AVAILABLE_PITCH: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.SENSOR_AVAILABLE_ROLL: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.SENSOR_AVAILABLE_CONDUCTIVITY: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.SENSOR_AVAILABLE_TEMPERATURE: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.BIN_1_DISTANCE: {'type': int, 'value': 60175 },
        ADCP_PD0_PARSED_KEY.TRANSMIT_PULSE_LENGTH: {'type': int, 'value': 4109 },
        ADCP_PD0_PARSED_KEY.REFERENCE_LAYER_START: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.REFERENCE_LAYER_STOP: {'type': int, 'value': 5 },
        ADCP_PD0_PARSED_KEY.FALSE_TARGET_THRESHOLD: {'type': int, 'value': 50 },
        ADCP_PD0_PARSED_KEY.LOW_LATENCY_TRIGGER: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.TRANSMIT_LAG_DISTANCE: {'type': int, 'value': 50688 },
        ADCP_PD0_PARSED_KEY.CPU_BOARD_SERIAL_NUMBER: {'type': long, 'value': 9367487254980977929L },
        ADCP_PD0_PARSED_KEY.SYSTEM_BANDWIDTH: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.SYSTEM_POWER: {'type': int, 'value': 255 },
        ADCP_PD0_PARSED_KEY.SERIAL_NUMBER: {'type': int, 'value': 206045184 },
        ADCP_PD0_PARSED_KEY.BEAM_ANGLE: {'type': int, 'value': 20 },
        ADCP_PD0_PARSED_KEY.VARIABLE_LEADER_ID: {'type': int, 'value': 128 },
        ADCP_PD0_PARSED_KEY.ENSEMBLE_NUMBER: {'type': int, 'value': 5 },
        ADCP_PD0_PARSED_KEY.INTERNAL_TIMESTAMP: {'type': float, 'value': 752 },
        ADCP_PD0_PARSED_KEY.ENSEMBLE_NUMBER_INCREMENT: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.BIT_RESULT_DEMOD_0: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.BIT_RESULT_DEMOD_1: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.BIT_RESULT_TIMING: {'type': int, 'value': 0  },
        ADCP_PD0_PARSED_KEY.SPEED_OF_SOUND: {'type': int, 'value': 1523 },
        ADCP_PD0_PARSED_KEY.TRANSDUCER_DEPTH: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.HEADING: {'type': int, 'value': 5221 },
        ADCP_PD0_PARSED_KEY.PITCH: {'type': int, 'value': -4657 },
        ADCP_PD0_PARSED_KEY.ROLL: {'type': int, 'value': -4561 },
        ADCP_PD0_PARSED_KEY.SALINITY: {'type': int, 'value': 35 },
        ADCP_PD0_PARSED_KEY.TEMPERATURE: {'type': int, 'value': 2050     },
        ADCP_PD0_PARSED_KEY.MPT_MINUTES: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.MPT_SECONDS: {'type': float, 'value': 0.0 },
        ADCP_PD0_PARSED_KEY.HEADING_STDEV: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.PITCH_STDEV: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.ROLL_STDEV: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.ADC_TRANSMIT_CURRENT: {'type': int, 'value': 116 },
        ADCP_PD0_PARSED_KEY.ADC_TRANSMIT_VOLTAGE: {'type': int, 'value': 169 },
        ADCP_PD0_PARSED_KEY.ADC_AMBIENT_TEMP: {'type': int, 'value': 88 },
        ADCP_PD0_PARSED_KEY.ADC_PRESSURE_PLUS: {'type': int, 'value': 79 },
        ADCP_PD0_PARSED_KEY.ADC_PRESSURE_MINUS: {'type': int, 'value': 79 },
        ADCP_PD0_PARSED_KEY.ADC_ATTITUDE_TEMP: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.ADC_ATTITUDE: {'type': int, 'value': 0   },
        ADCP_PD0_PARSED_KEY.ADC_CONTAMINATION_SENSOR: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.BUS_ERROR_EXCEPTION: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.ADDRESS_ERROR_EXCEPTION: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.ILLEGAL_INSTRUCTION_EXCEPTION: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.ZERO_DIVIDE_INSTRUCTION: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.EMULATOR_EXCEPTION: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.UNASSIGNED_EXCEPTION: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.WATCHDOG_RESTART_OCCURED: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.BATTERY_SAVER_POWER: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.PINGING: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.COLD_WAKEUP_OCCURED: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.UNKNOWN_WAKEUP_OCCURED: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.CLOCK_READ_ERROR: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.UNEXPECTED_ALARM: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.CLOCK_JUMP_FORWARD: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.CLOCK_JUMP_BACKWARD: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.POWER_FAIL: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.SPURIOUS_DSP_INTERRUPT: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.SPURIOUS_UART_INTERRUPT: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.SPURIOUS_CLOCK_INTERRUPT: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.LEVEL_7_INTERRUPT: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.ABSOLUTE_PRESSURE: {'type': int, 'value': 4294963793 },
        ADCP_PD0_PARSED_KEY.PRESSURE_VARIANCE: {'type': int, 'value': 0 },
        ADCP_PD0_PARSED_KEY.INTERNAL_TIMESTAMP: {'type': float, 'value': 1363408382.02 },
        ADCP_PD0_PARSED_KEY.VELOCITY_DATA_ID: {'type': int, 'value': 1 },
        ADCP_PD0_PARSED_KEY.CORRELATION_MAGNITUDE_ID: {'type': int, 'value': 2 },
        ADCP_PD0_PARSED_KEY.CORRELATION_MAGNITUDE_BEAM1: {'type': list, 'value': [19801, 1796, 1800, 1797, 1288, 1539, 1290, 1543, 1028, 1797, 1538, 775, 1034, 1283, 1029, 1799, 1801, 1545, 519, 772, 519, 1033, 1028, 1286, 521, 519, 1545, 1801, 522, 1286, 1030, 1032, 1542, 1035, 1283, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.CORRELATION_MAGNITUDE_BEAM2: {'type': list, 'value': [22365, 2057, 2825, 2825, 1801, 2058, 1545, 1286, 3079, 522, 1547, 519, 2052, 2820, 519, 1806, 1026, 1547, 1795, 1801, 2311, 1030, 781, 1796, 1037, 1802, 1035, 1798, 770, 2313, 1292, 1031, 1030, 2830, 523, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.CORRELATION_MAGNITUDE_BEAM3: {'type': list, 'value': [3853, 1796, 1289, 1803, 2317, 2571, 1028, 1282, 1799, 2825, 2574, 1026, 1028, 518, 1290, 1286, 1032, 1797, 1028, 2312, 1031, 775, 1549, 772, 1028, 772, 2570, 1288, 1796, 1542, 1538, 777, 1282, 773, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.CORRELATION_MAGNITUDE_BEAM4: {'type': list, 'value': [5386, 4100, 2822, 1286, 774, 1799, 518, 778, 3340, 1031, 1546, 1545, 1547, 2566, 3077, 3334, 1801, 1809, 2058, 1539, 1798, 1546, 3593, 1032, 2307, 1025, 1545, 2316, 2055, 1546, 1292, 2312, 1035, 2316, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.ECHO_INTENSITY_ID: {'type': int, 'value': 3 },
        ADCP_PD0_PARSED_KEY.ECHO_INTENSITY_BEAM1: {'type': list, 'value': [24925, 10538, 10281, 10537, 10282, 10281, 10281, 10282, 10282, 10281, 10281, 10281, 10538, 10282, 10281, 10282, 10281, 10537, 10281, 10281, 10281, 10281, 10281, 10281, 10281, 10281, 10281, 10281, 10281, 10282, 10281, 10282, 10537, 10281, 10281, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.ECHO_INTENSITY_BEAM2: {'type': list, 'value': [29027, 12334, 12334, 12078, 12078, 11821, 12334, 12334, 12078, 12078, 12078, 12078, 12078, 12078, 12078, 12079, 12334, 12078, 12334, 12333, 12078, 12333, 12078, 12077, 12078, 12078, 12078, 12334, 12077, 12078, 12078, 12078, 12078, 12078, 12078, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.ECHO_INTENSITY_BEAM3: {'type': list, 'value': [12079, 10282, 10281, 10281, 10282, 10281, 10282, 10282, 10281, 10025, 10282, 10282, 10282, 10282, 10025, 10282, 10281, 10025, 10281, 10281, 10282, 10281, 10282, 10281, 10281, 10281, 10537, 10282, 10281, 10281, 10281, 10281, 10281, 10282, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.ECHO_INTENSITY_BEAM4: {'type': list, 'value': [14387, 12334, 12078, 12078, 12078, 12334, 12078, 12334, 12078, 12078, 12077, 12077, 12334, 12078, 12334, 12078, 12334, 12077, 12078, 11821, 12335, 12077, 12078, 12077, 12334, 11822, 12334, 12334, 12077, 12077, 12078, 11821, 11821, 12078, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.PERCENT_GOOD_ID: {'type': int, 'value': 4 },
        ADCP_PD0_PARSED_KEY.CHECKSUM: {'type': int, 'value': 8239 }
    }

    # red
    _coordinate_transformation_earth_parameters = {
        # Earth Coordinates
        ADCP_PD0_PARSED_KEY.WATER_VELOCITY_EAST: {'type': list, 'value': [128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128] },
        ADCP_PD0_PARSED_KEY.WATER_VELOCITY_NORTH: {'type': list, 'value': [128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128] },
        ADCP_PD0_PARSED_KEY.WATER_VELOCITY_UP: {'type': list, 'value': [128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128] },
        ADCP_PD0_PARSED_KEY.ERROR_VELOCITY: {'type': list, 'value': [128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128] },
        ADCP_PD0_PARSED_KEY.PERCENT_GOOD_3BEAM: {'type': list, 'value': [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.PERCENT_TRANSFORMS_REJECT: {'type': list, 'value': [25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600] },
        ADCP_PD0_PARSED_KEY.PERCENT_BAD_BEAMS: {'type': list, 'value': [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.PERCENT_GOOD_4BEAM: {'type': list, 'value': [25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600, 25600] },
    }

    # blue
    _coordinate_transformation_beam_parameters = {
        # Beam Coordinates
        ADCP_PD0_PARSED_KEY.PERCENT_GOOD_BEAM1: {'type': list, 'value': [25700, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.PERCENT_GOOD_BEAM2: {'type': list, 'value': [25700, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.PERCENT_GOOD_BEAM3: {'type': list, 'value': [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.PERCENT_GOOD_BEAM4: {'type': list, 'value': [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        ADCP_PD0_PARSED_KEY.BEAM_1_VELOCITY: {'type': list, 'value': [4864, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128] },
        ADCP_PD0_PARSED_KEY.BEAM_2_VELOCITY: {'type': list, 'value': [62719, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128] },
        ADCP_PD0_PARSED_KEY.BEAM_3_VELOCITY: {'type': list, 'value': [45824, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128] },
        ADCP_PD0_PARSED_KEY.BEAM_4_VELOCITY  : {'type': list, 'value': [19712, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128, 128] },
    }

    _pd0_parameters = dict(_pd0_parameters_base.items() +
                           _coordinate_transformation_beam_parameters.items())
    _pd0_parameters_earth = dict(_pd0_parameters_base.items() +
                           _coordinate_transformation_earth_parameters.items())
    
    # Driver Parameter Methods
    ###
    def assert_driver_parameters(self, current_parameters, verify_values = False):
        """
        Verify that all driver parameters are correct and potentially verify values.
        @param current_parameters: driver parameters read from the driver instance
        @param verify_values: should we verify values against definition?
        """
        log.debug("assert_driver_parameters current_parameters = " + str(current_parameters))
        self.assert_parameters(current_parameters, self._driver_parameters, verify_values)

    ###
    # Data Particle Parameters Methods
    ###
    def assert_sample_data_particle(self, data_particle):
        '''
        Verify a particle is a know particle to this driver and verify the particle is  correct
        @param data_particle: Data particle of unkown type produced by the driver
        '''

        if (isinstance(data_particle, DataParticleType.ADCP_PD0_PARSED_BEAM)):
            self.assert_particle_pd0_data(data_particle)
        elif (isinstance(data_particle, DataParticleType.ADCP_SYSTEM_CONFIGURATION)):
            self.assert_particle_system_configuration(data_particle)
        elif (isinstance(data_particle, DataParticleType.ADCP_COMPASS_CALIBRATION)):
            self.assert_particle_compass_calibration(data_particle)
        else:
            log.error("Unknown Particle Detected: %s" % data_particle)
            self.assertFalse(True)

    def assert_particle_compass_calibration(self, data_particle, verify_values = True):
        '''
        Verify an adcpt calibration data particle
        @param data_particle: ADCPT_CalibrationDataParticle data particle
        @param verify_values: bool, should we verify parameter values
        '''
        log.debug("in assert_particle_compass_calibration")
        self.assert_data_particle_header(data_particle, DataParticleType.ADCP_COMPASS_CALIBRATION)
        self.assert_data_particle_parameters(data_particle, self._calibration_data_parameters, verify_values)

    def assert_particle_system_configuration(self, data_particle, verify_values = True):
        '''
        Verify an adcpt fd data particle
        @param data_particle: ADCPT_FDDataParticle data particle
        @param verify_values: bool, should we verify parameter values
        '''
        self.assert_data_particle_header(data_particle, DataParticleType.ADCP_SYSTEM_CONFIGURATION)
        self.assert_data_particle_parameters(data_particle, self._system_configuration_data_parameters, verify_values)

    def assert_particle_pd0_data(self, data_particle, verify_values = True):
        '''
        Verify an adcpt ps0 data particle
        @param data_particle: ADCPT_PS0DataParticle data particle
        @param verify_values: bool, should we verify parameter values
        '''
        log.debug("IN assert_particle_pd0_data")
        self.assert_data_particle_header(data_particle, DataParticleType.ADCP_PD0_PARSED_BEAM)
        self.assert_data_particle_parameters(data_particle, self._pd0_parameters) # , verify_values

    def assert_particle_pd0_data_earth(self, data_particle, verify_values = True):
        '''
        Verify an adcpt ps0 data particle
        @param data_particle: ADCPT_PS0DataParticle data particle
        @param verify_values: bool, should we verify parameter values
        '''
        log.debug("IN assert_particle_pd0_data")
        self.assert_data_particle_header(data_particle, DataParticleType.ADCP_PD0_PARSED_EARTH)
        self.assert_data_particle_parameters(data_particle, self._pd0_parameters_earth) # , verify_values

###############################################################################
#                                UNIT TESTS                                   #
#         Unit tests test the method calls and parameters using Mock.         #
###############################################################################
@attr('UNIT', group='mi')
class UnitFromIDK(WorkhorseDriverUnitTest, ADCPTMixin):
    def setUp(self):
        WorkhorseDriverUnitTest.setUp(self)

    def test_driver_schema(self):
        """
        get the driver schema and verify it is configured properly
        """
        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_driver_schema(driver, self._driver_parameters, self._driver_capabilities)

    def test_got_data(self):
        """
        Verify sample data passed through the got data method produces the correct data particles
        """
        # Create and initialize the instrument driver with a mock port agent
        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_initialize_driver(driver)

        self.assert_raw_particle_published(driver, True)

        # Start validating data particles

        self.assert_particle_published(driver, RSN_CALIBRATION_RAW_DATA, self.assert_particle_compass_calibration, True)
        self.assert_particle_published(driver, RSN_PS0_RAW_DATA, self.assert_particle_system_configuration, True)
        self.assert_particle_published(driver, RSN_SAMPLE_RAW_DATA, self.assert_particle_pd0_data, True)

    def test_driver_parameters(self):
        """
        Verify the set of parameters known by the driver
        """
        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_initialize_driver(driver, ProtocolState.COMMAND)

        expected_parameters = sorted(self._driver_parameters.keys())
        reported_parameters = sorted(driver.get_resource(Parameter.ALL))

        log.debug("*** Expected Parameters: %s" % expected_parameters)
        log.debug("*** Reported Parameters: %s" % reported_parameters)

        self.assertEqual(reported_parameters, expected_parameters)

        # Verify the parameter definitions
        self.assert_driver_parameter_definition(driver, self._driver_parameters)

    def test_capabilities(self):
        """
        Verify the FSM reports capabilities as expected.  All states defined in this dict must
        also be defined in the protocol FSM.
        """

        capabilities = {
            ProtocolState.UNKNOWN: ['DRIVER_EVENT_DISCOVER'],
            ProtocolState.COMMAND: ['DRIVER_EVENT_CLOCK_SYNC',
                                    'DRIVER_EVENT_GET',
                                    'DRIVER_EVENT_INIT_PARAMS',
                                    'DRIVER_EVENT_SET',
                                    'DRIVER_EVENT_START_AUTOSAMPLE',
                                    'DRIVER_EVENT_START_DIRECT',
                                    'DRIVER_EVENT_ACQUIRE_STATUS',
                                    'PROTOCOL_EVENT_CLEAR_ERROR_STATUS_WORD',
                                    'PROTOCOL_EVENT_CLEAR_FAULT_LOG',
                                    'PROTOCOL_EVENT_GET_CALIBRATION',
                                    'PROTOCOL_EVENT_GET_CONFIGURATION',
                                    'PROTOCOL_EVENT_GET_ERROR_STATUS_WORD',
                                    'PROTOCOL_EVENT_GET_FAULT_LOG',
                                    'PROTOCOL_EVENT_RECOVER_AUTOSAMPLE',
                                    'FACTORY_DEFAULT_SETTINGS',
                                    'USER_DEFAULT_SETTINGS',
                                    'PROTOCOL_EVENT_RUN_TEST_200',
                                    'PROTOCOL_EVENT_SAVE_SETUP_TO_RAM',
                                    'PROTOCOL_EVENT_SCHEDULED_CLOCK_SYNC'],
            ProtocolState.AUTOSAMPLE: ['DRIVER_EVENT_DISCOVER',
                                       'DRIVER_EVENT_STOP_AUTOSAMPLE',
                                       'DRIVER_EVENT_GET',
                                       'DRIVER_EVENT_INIT_PARAMS',
                                       'PROTOCOL_EVENT_GET_CALIBRATION',
                                       'PROTOCOL_EVENT_GET_CONFIGURATION',
                                       'PROTOCOL_EVENT_SCHEDULED_CLOCK_SYNC'],
            ProtocolState.DIRECT_ACCESS: ['DRIVER_EVENT_STOP_DIRECT', 'EXECUTE_DIRECT']
        }
        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_capabilities(driver, capabilities)


    def test_driver_enums(self):
        """
        Verify that all driver enumeration has no duplicate values that might cause confusion.  Also
        do a little extra validation for the Capabilites
        """

        self.assert_enum_has_no_duplicates(InstrumentCmds())
        self.assert_enum_has_no_duplicates(ProtocolState())
        self.assert_enum_has_no_duplicates(ProtocolEvent())
        self.assert_enum_has_no_duplicates(Parameter())
        self.assert_enum_has_no_duplicates(DataParticleType())
        self.assert_enum_has_no_duplicates(ScheduledJob())
        # Test capabilites for duplicates, them verify that capabilities is a subset of proto events
        self.assert_enum_has_no_duplicates(Capability())
        self.assert_enum_complete(Capability(), ProtocolEvent())

    def test_chunker(self):
        """
        Test the chunker and verify the particles created.
        """
        chunker = StringChunker(Protocol.sieve_function)

        self.assert_chunker_sample(chunker, RSN_SAMPLE_RAW_DATA)
        self.assert_chunker_sample_with_noise(chunker, RSN_SAMPLE_RAW_DATA)
        self.assert_chunker_fragmented_sample(chunker, RSN_SAMPLE_RAW_DATA, 32)
        self.assert_chunker_combined_sample(chunker, RSN_SAMPLE_RAW_DATA)

        self.assert_chunker_sample(chunker, RSN_PS0_RAW_DATA)
        self.assert_chunker_sample_with_noise(chunker, RSN_PS0_RAW_DATA)
        self.assert_chunker_fragmented_sample(chunker, RSN_PS0_RAW_DATA, 32)
        self.assert_chunker_combined_sample(chunker, RSN_PS0_RAW_DATA)

        self.assert_chunker_sample(chunker, RSN_CALIBRATION_RAW_DATA)
        self.assert_chunker_sample_with_noise(chunker, RSN_CALIBRATION_RAW_DATA)
        self.assert_chunker_fragmented_sample(chunker, RSN_CALIBRATION_RAW_DATA, 32)
        self.assert_chunker_combined_sample(chunker, RSN_CALIBRATION_RAW_DATA)

    def test_protocol_filter_capabilities(self):
        """
        This tests driver filter_capabilities.
        Iterate through available capabilities, and verify that they can pass successfully through the filter.
        Test silly made up capabilities to verify they are blocked by filter.
        """
        my_event_callback = Mock(spec="UNKNOWN WHAT SHOULD GO HERE FOR evt_callback")
        protocol = Protocol(Prompt, NEWLINE, my_event_callback)
        driver_capabilities = Capability().list()
        test_capabilities = Capability().list()

        # Add a bogus capability that will be filtered out.
        test_capabilities.append("BOGUS_CAPABILITY")

        # Verify "BOGUS_CAPABILITY was filtered out
        self.assertEquals(driver_capabilities, protocol._filter_capabilities(test_capabilities))


###############################################################################
#                            INTEGRATION TESTS                                #
#     Integration test test the direct driver / instrument interaction        #
#     but making direct calls via zeromq.                                     #
#     - Common Integration tests test the driver through the instrument agent #
#     and common for all drivers (minimum requirement for ION ingestion)      #
###############################################################################
@attr('INT', group='mi')
class IntFromIDK(WorkhorseDriverIntegrationTest, ADCPTMixin):

    def setUp(self):
        self.port_agents = {}
        InstrumentDriverIntegrationTestCase.setUp(self)

    def create_serial_comm_config(self, comm_config):
        return {
            'instrument_type': ConfigTypes.SERIAL,
            'port_agent_addr': comm_config.host,
            'device_os_port': comm_config.device_os_port,
            'device_baud': comm_config.device_baud,
            'device_data_bits': comm_config.device_data_bits,
            'device_stop_bits': comm_config.device_stop_bits,
            'device_flow_control': comm_config.device_flow_control,
            'device_parity': comm_config.device_parity,
            'command_port': comm_config.command_port,
            'data_port': comm_config.data_port,
            'telnet_sniffer_port': comm_config.sniffer_port,
            'process_type': PortAgentProcessType.UNIX,
            'log_level': 5,
        }

    def create_ethernet_comm_config(self, comm_config):
        config = {
            'instrument_type': ConfigTypes.ETHERNET,
            'port_agent_addr': comm_config.host,
            'device_addr': comm_config.device_addr,
            'device_port': comm_config.device_port,
            'command_port': comm_config.command_port,
            'data_port': comm_config.data_port,
            'telnet_sniffer_port': comm_config.sniffer_port,
            'process_type': PortAgentProcessType.UNIX,
            'log_level': 5,
        }
        log.debug('create_ethernet_comm_config returning: %r', config)
        return config

    def create_botpt_comm_config(self, comm_config):
        config = self.create_ethernet_comm_config(comm_config)
        config['instrument_type'] = ConfigTypes.BOTPT
        config['device_tx_port'] = comm_config.device_tx_port
        config['device_rx_port'] = comm_config.device_rx_port
        return config

    def create_multi_comm_config(self, comm_config):
        result = {}
        for name, config in comm_config.configs.items():
            if config.method() == ConfigTypes.ETHERNET:
                result[name] = self.create_ethernet_comm_config(config)
            elif config.method() == ConfigTypes.SERIAL:
                result[name] = self.create_serial_comm_config(config)
        return result

    def port_agent_config(self):
        """
        return the port agent configuration
        """
        comm_config = self.get_comm_config()
        log.debug('comm_config = %r', comm_config.__dict__)
        method = comm_config.method()
        config = {}

        if method == ConfigTypes.SERIAL:
            config = self.create_serial_comm_config(comm_config)
        elif method == ConfigTypes.ETHERNET:
            config = self.create_ethernet_comm_config(comm_config)
        elif method == ConfigTypes.BOTPT:
            config = self.create_botpt_comm_config(comm_config)
        elif method == ConfigTypes.MULTI:
            config = self.create_multi_comm_config(comm_config)

        config['instrument_type'] = comm_config.method()

        if comm_config.sniffer_prefix: config['telnet_sniffer_prefix'] = comm_config.sniffer_prefix
        if comm_config.sniffer_suffix: config['telnet_sniffer_suffix'] = comm_config.sniffer_suffix

        return config

    def init_port_agent(self):
        """
        @brief Launch the driver process and driver client.  This is used in the
        integration and qualification tests.  The port agent abstracts the physical
        interface with the instrument.
        @retval return the pid to the logger process
        """
        if self.port_agents:
            log.error("Port agent already initialized")
            return

        log.debug("Startup Port Agent")

        config = self.port_agent_config()
        log.debug("port agent config: %s", config)

        port_agents = {}

        if config['instrument_type'] != ConfigTypes.MULTI:
            config = {'only one port agent here!': config}
        for name, each in config.items():
            log.error("Sung init port agent name %s", name)
            log.error("Sung init port agent each %s", each)
            if type(each) != dict:
                continue
            port_agent_host = each.get('device_addr')
            log.error("Sung init port agant host %s", port_agent_host)
            if port_agent_host is not None:
                log.error("Sung init port agant calling launch_process")
                port_agent = PortAgentProcess.launch_process(each, timeout=60, test_mode=True)
                log.error("Sung init port agant  after")
                port = port_agent.get_data_port()
                log.error("Sung init port agant port %s", port)
                pid = port_agent.get_pid()

                if port_agent_host == LOCALHOST:
                    log.info('Started port agent pid %s listening at port %s' % (pid, port))
                else:
                    log.info("Connecting to port agent on host: %s, port: %s", port_agent_host, port)
                log.error("Sung init port agant port agent %s", repr(port_agent))
                port_agents[name] = port_agent

        self.addCleanup(self.stop_port_agent)
        self.port_agents = port_agents

    def stop_port_agent(self):
        """
        Stop the port agent.
        """
        log.info("Stop port agent")
        if self.port_agents:
            log.debug("found port agents, now stop them")
            for agent in self.port_agents.values():
                agent.stop()
        self.port_agents = {}

    def port_agent_comm_config(self):
        config = {}
        for name, each in self.port_agents.items():
            log.debug('XXXXX: %r', each.__dict__)
            port = each.get_data_port()
            cmd_port = each.get_command_port()

            config[name] = {
                # TODO
                'addr': each._config['port_agent_addr'],
                'port': port,
                'cmd_port': cmd_port
            }
        return config

    def _test_autosample_particle_generation(self):
        """
        Test that we can generate particles when in autosample
        """
        self.assert_initialize_driver()

        params = {
            Parameter.INSTRUMENT_ID: 0,
            Parameter.SLEEP_ENABLE: 0,
            Parameter.POLLED_MODE: False,
            Parameter.XMIT_POWER: 255,
            Parameter.SPEED_OF_SOUND: 1485,
            Parameter.PITCH: 0,
            Parameter.ROLL: 0,
            Parameter.SALINITY: 35,
            Parameter.TIME_PER_ENSEMBLE: '00:00:20.00',
            Parameter.TIME_PER_PING: '00:01.00',
            Parameter.FALSE_TARGET_THRESHOLD: '050,001',
            Parameter.BANDWIDTH_CONTROL: 0,
            Parameter.CORRELATION_THRESHOLD: 64,
            Parameter.ERROR_VELOCITY_THRESHOLD: 2000,
            Parameter.BLANK_AFTER_TRANSMIT: 704,
            Parameter.CLIP_DATA_PAST_BOTTOM: 0,
            Parameter.RECEIVER_GAIN_SELECT: 1,
            Parameter.NUMBER_OF_DEPTH_CELLS: 100,
            Parameter.PINGS_PER_ENSEMBLE: 1,
            Parameter.DEPTH_CELL_SIZE: 800,
            Parameter.TRANSMIT_LENGTH: 0,
            Parameter.PING_WEIGHT: 0,
            Parameter.AMBIGUITY_VELOCITY: 175,
            Parameter.SERIAL_DATA_OUT: '000 000 000',
            Parameter.LATENCY_TRIGGER: 0,
            Parameter.HEADING_ALIGNMENT: '+00000',
            Parameter.HEADING_BIAS: '+00000',
            Parameter.TRANSDUCER_DEPTH:8000,
            Parameter.DATA_STREAM_SELECTION:0,
            Parameter.ENSEMBLE_PER_BURST:0,
            Parameter.BUFFERED_OUTPUT_PERIOD:'00:00:00',
            Parameter.SAMPLE_AMBIENT_SOUND:0,

        }
        self.assert_set_bulk(params)

        self.assert_driver_command(ProtocolEvent.START_AUTOSAMPLE, state=ProtocolState.AUTOSAMPLE, delay=1)
        self.assert_async_particle_generation(DataParticleType.ADCP_PD0_PARSED_BEAM, self.assert_particle_pd0_data, timeout=40)

        self.assert_driver_command(ProtocolEvent.STOP_AUTOSAMPLE, state=ProtocolState.COMMAND, delay=10)

    def _test_test_set_instrument_id(self):
        self.assert_initialize_driver()
        self._test_set_instrument_id()

    def _test_test_set_sleep_enable(self):
        self.assert_initialize_driver()
        self._test_set_sleep_enable()

    def _test_test_set_polled_mode(self):
        self.assert_initialize_driver()
        self._test_set_polled_mode()

    def _test_test_set_xmit_power(self):
        self.assert_initialize_driver()
        self._test_set_xmit_power()

    def _test_test_set_pitch(self):
        self.assert_initialize_driver()
        self._test_set_pitch()

    def _test_test_set_roll(self):
        self.assert_initialize_driver()
        self._test_set_roll()

    def _test_test_set_salinity(self):
        self.assert_initialize_driver()
        self._test_set_salinity()

    def _test_test_set_coordinate_transformation(self):
        self.assert_initialize_driver()
        self._test_set_coordinate_transformation()

    def _test_test_set_sensor_source(self):
        self.assert_initialize_driver()
        self._test_set_sensor_source()

    def _test_test_set_time_per_ensemble(self):
        self.assert_initialize_driver()
        self._test_set_time_per_ensemble()

    def _test_test_set_time_per_ping(self):
        self.assert_initialize_driver()
        self._test_set_time_per_ping()

    def _test_test_set_false_target_threshold(self):
        self.assert_initialize_driver()
        self._test_set_false_target_threshold()

    def _test_test_set_bandwidth_control(self):
        self.assert_initialize_driver()
        self._test_set_bandwidth_control()

    def _test_test_set_correlation_threshold(self):
        self.assert_initialize_driver()
        self._test_set_correlation_threshold()

    def _test_test_set_error_velocity_threshold(self):
        self.assert_initialize_driver()
        self._test_set_error_velocity_threshold()

    def _test_test_set_blank_after_transmit(self):
        self.assert_initialize_driver()
        self._test_set_blank_after_transmit()

    def _test_test_set_clip_data_past_bottom(self):
        self.assert_initialize_driver()
        self._test_set_clip_data_past_bottom()

    def _test_test_set_receiver_gain_select(self):
        self.assert_initialize_driver()
        self._test_set_receiver_gain_select()

    def _test_test_set_water_reference_layer(self):
        self.assert_initialize_driver()
        self._test_set_water_reference_layer()

    def _test_test_set_number_of_depth_cells(self):
        self.assert_initialize_driver()
        self._test_set_number_of_depth_cells()

    def _test_test_set_pings_per_ensemble(self):
        self.assert_initialize_driver()
        self._test_set_pings_per_ensemble()

    def _test_test_set_depth_cell_size(self):
        self.assert_initialize_driver()
        self._test_set_depth_cell_size()

    def _test_test_set_transmit_length(self):
        self.assert_initialize_driver()
        self._test_set_transmit_length()

    def _test_test_set_ping_weight(self):
        self.assert_initialize_driver()
        self._test_set_ping_weight()

    def _test_test_set_ambiguity_velocity(self):
        self.assert_initialize_driver()
        self._test_set_ambiguity_velocity()

    def _test_test_set_serial_data_out_readonly(self):
        self.assert_initialize_driver()
        self._test_set_serial_data_out_readonly()

    def _test_test_set_serial_flow_control_readonly(self):
        self.assert_initialize_driver()
        self._test_set_serial_flow_control_readonly()

    def _test_test_set_banner_readonly(self):
        self.assert_initialize_driver()
        self._test_set_banner_readonly()

    def _test_test_set_save_nvram_to_recorder_readonly(self):
        self.assert_initialize_driver()
        self._test_set_save_nvram_to_recorder_readonly()

    def _test_test_set_serial_out_fw_switches_readonly(self):
        self.assert_initialize_driver()
        self._test_set_serial_out_fw_switches_readonly()

    def _test_test_set_water_profiling_mode_readonly(self):
        self.assert_initialize_driver()
        self._test_set_water_profiling_mode_readonly()


    def _test_parameter_test_set(self):
        self.assert_initialize_driver()
        self._test_set_parameter_test()

    def _test_set_time_first_ping(self):
        self.assert_initialize_driver()
        self._test_set_time_of_first_ping_readonly()

    def _test_test_set_ranges(self):
        self.assert_initialize_driver()
        fail = False

        for k in self._tested.keys():
            if k not in self._driver_parameters.keys():
                log.error("*WARNING* " + k + " was tested but is not in _driver_parameters")
                #fail = True

        for k in self._driver_parameters.keys():
            if k not in [Parameter.TIME_OF_FIRST_PING, Parameter.TIME] + self._tested.keys():
                log.error("*ERROR* " + k + " is in _driver_parameters but was not tested.")
                fail = True

        self.assertFalse(fail, "See above for un-exercized parameters.")

    def test_scheduled_absolute_acquire_status_command(self):
        """
        Verify the scheduled clock sync is triggered and functions as expected
        """
        log.debug("IN test_scheduled_clock_sync_command")
        self.assert_initialize_driver()
        self.assert_set(TeledyneParameter.GET_STATUS_INTERVAL,'00:00:10')
        self.assert_async_particle_generation(DataParticleType.ADCP_COMPASS_CALIBRATION, self.assert_Calibration, timeout=60)
        self.assert_async_particle_generation(DataParticleType.ADCP_ANCILLARY_SYSTEM_DATA, self.assert_ANCILLARY_data, timeout=60)
        self.assert_async_particle_generation(DataParticleType.ADCP_TRANSMIT_PATH, self.assert_TRANSMIT_data, timeout=60)

        self.assert_async_particle_generation(DataParticleType.VADCP_COMPASS_CALIBRATION, self.assert_VADCP_Calibration, timeout=60)
        self.assert_async_particle_generation(DataParticleType.ADCP_ANCILLARY_SYSTEM_DATA, self.assert_VADCP_ANCILLARY_data, timeout=60)
        self.assert_async_particle_generation(DataParticleType.ADCP_TRANSMIT_PATH, self.assert_TRANSMIT_data, timeout=60)

        self.assert_set(TeledyneParameter.GET_STATUS_INTERVAL,'00:00:00')
        self.assert_current_state(TeledyneProtocolState.COMMAND)



    def test_acquire_status(self):
        """
        Verify the acquire_status command is functional
        """

        log.debug("IN test_acquire_status")
        self.assert_initialize_driver()
        self.assert_driver_command(TeledyneProtocolEvent.ACQUIRE_STATUS)

        self.assert_async_particle_generation(DataParticleType.ADCP_COMPASS_CALIBRATION, self.assert_Calibration, timeout=60)
        self.assert_async_particle_generation(DataParticleType.ADCP_ANCILLARY_SYSTEM_DATA, self.assert_VADCP_ANCILLARY_data, timeout=60)
        self.assert_async_particle_generation(DataParticleType.ADCP_TRANSMIT_PATH, self.assert_TRANSMIT_data, timeout=60)

        self.assert_async_particle_generation(DataParticleType.VADCP_COMPASS_CALIBRATION, self.assert_VADCP_Calibration, timeout=60)
        self.assert_async_particle_generation(DataParticleType.ADCP_ANCILLARY_SYSTEM_DATA, self.assert_VADCP_ANCILLARY_data, timeout=60)
        self.assert_async_particle_generation(DataParticleType.ADCP_TRANSMIT_PATH, self.assert_TRANSMIT_data, timeout=60)

    def assert_VADCP_TRANSMIT_data(self, data_particle, verify_values = True):
        '''
        Verify an adcpt ps0 data particle
        @param data_particle: ADCPT_PS0DataParticle data particle
        @param verify_values: bool, should we verify parameter values
        '''
        log.debug("IN assert_ADCP_TRANSMIT")
        self.assert_data_particle_header(data_particle, DataParticleType.VADCP_TRANSMIT_PATH)
        #self.assert_data_particle_parameters(data_particle, self._pd0_parameters) # , verify_values

    def assert_VADCP_ANCILLARY_data(self, data_particle, verify_values = True):
        '''
        Verify an adcpt ps0 data particle
        @param data_particle: ADCPT_PS0DataParticle data particle
        @param verify_values: bool, should we verify parameter values
        '''
        log.debug("IN assert_particle_pd0_data")
        self.assert_data_particle_header(data_particle, DataParticleType.VADCP_ANCILLARY_SYSTEM_DATA)
        #self.assert_data_particle_parameters(data_particle, self._pd0_parameters) # , verify_values

    def assert_VADCP_Calibration(self, data_particle, verify_values = True):
        log.debug("IN assert_Calibration")
        self.assert_data_particle_header(data_particle, DataParticleType.VADCP_COMPASS_CALIBRATION)


    def test_commands(self):
        """
        Run instrument commands from both command and streaming mode.
        """
        self.assert_initialize_driver()
        ####
        # First test in command mode
        ####
        self.assert_driver_command(TeledyneProtocolEvent.GET_CONFIGURATION)

        self.assert_driver_command(TeledyneProtocolEvent.START_AUTOSAMPLE, state=TeledyneProtocolState.AUTOSAMPLE, delay=10)
        self.assert_driver_command(TeledyneProtocolEvent.STOP_AUTOSAMPLE, state=TeledyneProtocolState.COMMAND, delay=1)
        self.assert_driver_command(TeledyneProtocolEvent.GET_CALIBRATION)
        self.assert_driver_command(TeledyneProtocolEvent.GET_CONFIGURATION)
        self.assert_driver_command(TeledyneProtocolEvent.CLOCK_SYNC)
        self.assert_driver_command(TeledyneProtocolEvent.SCHEDULED_CLOCK_SYNC)
        self.assert_driver_command(TeledyneProtocolEvent.SAVE_SETUP_TO_RAM, expected="Parameters saved as USER defaults")
        self.assert_driver_command(TeledyneProtocolEvent.GET_ERROR_STATUS_WORD, regex='^........')
        self.assert_driver_command(TeledyneProtocolEvent.CLEAR_ERROR_STATUS_WORD, regex='^Error Status Word Cleared')
        self.assert_driver_command(TeledyneProtocolEvent.GET_FAULT_LOG, regex='^Total Unique Faults   =.*')
        self.assert_driver_command(TeledyneProtocolEvent.CLEAR_FAULT_LOG, expected='FC ..........\r\n Fault Log Cleared.\r\nClearing buffer @0x00801000\r\nDone [i=2048].\r\n')
        self.assert_driver_command(TeledyneProtocolEvent.RUN_TEST_200, regex='^  Ambient  Temperature =')
        self.assert_driver_command(TeledyneProtocolEvent.USER_SETS)
        #self.assert_driver_command(TeledyneProtocolEvent.FACTORY_SETS)
        #self.assert_driver_command(TeledyneProtocolEvent.ACQUIRE_STATUS, regex='^4 beam status outputs')

        ####
        # Test in streaming mode
        ####
        # Put us in streaming
        self.assert_driver_command(TeledyneProtocolEvent.START_AUTOSAMPLE, state=TeledyneProtocolState.AUTOSAMPLE, delay=1)
        self.assert_driver_command_exception(TeledyneProtocolEvent.SAVE_SETUP_TO_RAM, exception_class=InstrumentCommandException)
        self.assert_driver_command_exception(TeledyneProtocolEvent.GET_ERROR_STATUS_WORD, exception_class=InstrumentCommandException)
        self.assert_driver_command_exception(TeledyneProtocolEvent.CLEAR_ERROR_STATUS_WORD, exception_class=InstrumentCommandException)
        self.assert_driver_command_exception(TeledyneProtocolEvent.GET_FAULT_LOG, exception_class=InstrumentCommandException)
        self.assert_driver_command_exception(TeledyneProtocolEvent.CLEAR_FAULT_LOG, exception_class=InstrumentCommandException)
        self.assert_driver_command_exception(TeledyneProtocolEvent.RUN_TEST_200, exception_class=InstrumentCommandException)
        self.assert_driver_command_exception(TeledyneProtocolEvent.ACQUIRE_STATUS, exception_class=InstrumentCommandException)
        self.assert_driver_command(TeledyneProtocolEvent.SCHEDULED_CLOCK_SYNC)
        self.assert_driver_command_exception(TeledyneProtocolEvent.CLOCK_SYNC, exception_class=InstrumentCommandException)
        self.assert_driver_command(TeledyneProtocolEvent.GET_CALIBRATION, regex=r'Calibration date and time:')
        self.assert_driver_command(TeledyneProtocolEvent.GET_CONFIGURATION, regex=r' Instrument S/N')
        self.assert_driver_command(TeledyneProtocolEvent.STOP_AUTOSAMPLE, state=TeledyneProtocolState.COMMAND, delay=1)

        ####
        # Test a bad command
        ####
        self.assert_driver_command_exception('ima_bad_command', exception_class=InstrumentCommandException)

    def _test_set_xmit_power_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for XMIT_POWER ======")


        # XMIT_POWER:  -- Int 0-255
        #log.error("****Sung *******  setting CQ to 0")
        self.assert_set(TeledyneParameter2.XMIT_POWER, 0)
        #log.error("****Sung *******  setting CQ to 128")

        self.assert_set(TeledyneParameter2.XMIT_POWER, 128)
        self.assert_set(TeledyneParameter2.XMIT_POWER, 254)

        self.assert_set_exception(TeledyneParameter2.XMIT_POWER, "LEROY JENKINS")
        self.assert_set_exception(TeledyneParameter2.XMIT_POWER, 256)
        self.assert_set_exception(TeledyneParameter2.XMIT_POWER, -1)

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.XMIT_POWER, self._driver_parameter_defaults[TeledyneParameter.XMIT_POWER])
        self.assert_set(TeledyneParameter2.XMIT_POWER, self._driver_parameters[TeledyneParameter2.XMIT_POWER][self.VALUE])
        self._tested[TeledyneParameter2.XMIT_POWER] = True

    def _test_set_speed_of_sound_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for SPEED_OF_SOUND ======")

        # SPEED_OF_SOUND:  -- Int 1485 (1400 - 1600)
        self.assert_set(TeledyneParameter2.SPEED_OF_SOUND, 1400)
        self.assert_set(TeledyneParameter2.SPEED_OF_SOUND, 1450)
        self.assert_set(TeledyneParameter2.SPEED_OF_SOUND, 1500)
        self.assert_set(TeledyneParameter2.SPEED_OF_SOUND, 1550)
        self.assert_set(TeledyneParameter2.SPEED_OF_SOUND, 1600)

        self.assert_set_exception(TeledyneParameter2.SPEED_OF_SOUND, 0)
        self.assert_set_exception(TeledyneParameter2.SPEED_OF_SOUND, 1399)
        self.assert_set_exception(TeledyneParameter2.SPEED_OF_SOUND, 1601)
        self.assert_set_exception(TeledyneParameter2.SPEED_OF_SOUND, "LEROY JENKINS")
        self.assert_set_exception(TeledyneParameter2.SPEED_OF_SOUND, -256)
        self.assert_set_exception(TeledyneParameter2.SPEED_OF_SOUND, -1)
        self.assert_set_exception(TeledyneParameter2.SPEED_OF_SOUND, 3.1415926)

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.SPEED_OF_SOUND, self._driver_parameter_defaults[TeledyneParameter.SPEED_OF_SOUND])
        self.assert_set(TeledyneParameter2.SPEED_OF_SOUND, self._driver_parameters[TeledyneParameter2.SPEED_OF_SOUND][self.VALUE])
        self._tested[TeledyneParameter2.SPEED_OF_SOUND] = True

    def _test_set_salinity_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for SALINITY ======")

        # SALINITY:  -- Int (0 - 40)
        self.assert_set(TeledyneParameter2.SALINITY, 1)
        self.assert_set(TeledyneParameter2.SALINITY, 10)
        self.assert_set(TeledyneParameter2.SALINITY, 20)
        self.assert_set(TeledyneParameter2.SALINITY, 30)
        self.assert_set(TeledyneParameter2.SALINITY, 40)

        self.assert_set_exception(TeledyneParameter2.SALINITY, "LEROY JENKINS")

        # AssertionError: Unexpected exception: ES no value match (40 != -1)
        self.assert_set_exception(TeledyneParameter2.SALINITY, -1)

        # AssertionError: Unexpected exception: ES no value match (35 != 41)
        self.assert_set_exception(TeledyneParameter2.SALINITY, 41)

        self.assert_set_exception(TeledyneParameter2.SALINITY, 3.1415926)

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.SALINITY, self._driver_parameter_defaults[TeledyneParameter.SALINITY])
        self.assert_set(TeledyneParameter2.SALINITY, self._driver_parameters[TeledyneParameter2.SALINITY][self.VALUE])
        self._tested[TeledyneParameter2.SALINITY] = True

    def _test_set_sensor_source_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for SENSOR_SOURCE ======")

        # SENSOR_SOURCE:  -- (0/1) for 7 positions.
        # note it lacks capability to have a 1 in the #6 position
        self.assert_set(TeledyneParameter2.SENSOR_SOURCE, "0000000")
        self.assert_set(TeledyneParameter2.SENSOR_SOURCE, "1111101")
        self.assert_set(TeledyneParameter2.SENSOR_SOURCE, "1010101")
        self.assert_set(TeledyneParameter2.SENSOR_SOURCE, "0101000")
        self.assert_set(TeledyneParameter2.SENSOR_SOURCE, "1100100")

        #
        # Reset to good value.
        #
        self.assert_set(TeledyneParameter2.SENSOR_SOURCE, "1111101")

        self.assert_set_exception(TeledyneParameter2.SENSOR_SOURCE, "LEROY JENKINS")
        self.assert_set_exception(TeledyneParameter2.SENSOR_SOURCE, 2)
        self.assert_set_exception(TeledyneParameter2.SENSOR_SOURCE, -1)
        self.assert_set_exception(TeledyneParameter2.SENSOR_SOURCE, "1111112")
        self.assert_set_exception(TeledyneParameter2.SENSOR_SOURCE, "11111112")
        self.assert_set_exception(TeledyneParameter2.SENSOR_SOURCE, 3.1415926)

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.SENSOR_SOURCE, self._driver_parameter_defaults[TeledyneParameter.SENSOR_SOURCE])
        self.assert_set(TeledyneParameter2.SENSOR_SOURCE, self._driver_parameters[TeledyneParameter2.SENSOR_SOURCE][self.VALUE])
        self._tested[TeledyneParameter2.SENSOR_SOURCE] = True

    def _test_set_time_per_ensemble_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for TIME_PER_ENSEMBLE ======")

        # TIME_PER_ENSEMBLE:  -- String 01:00:00.00 (hrs:min:sec.sec/100)
        self.assert_set(TeledyneParameter2.TIME_PER_ENSEMBLE, "00:00:00.00")
        self.assert_set(TeledyneParameter2.TIME_PER_ENSEMBLE, "00:00:01.00")
        self.assert_set(TeledyneParameter2.TIME_PER_ENSEMBLE, "00:01:00.00")

        self.assert_set_exception(TeledyneParameter2.TIME_PER_ENSEMBLE, '30:30:30.30')
        self.assert_set_exception(TeledyneParameter2.TIME_PER_ENSEMBLE, '59:59:59.99')
        self.assert_set_exception(TeledyneParameter2.TIME_PER_ENSEMBLE, "LEROY JENKINS")
        self.assert_set_exception(TeledyneParameter2.TIME_PER_ENSEMBLE, 2)
        self.assert_set_exception(TeledyneParameter2.TIME_PER_ENSEMBLE, -1)
        self.assert_set_exception(TeledyneParameter2.TIME_PER_ENSEMBLE, '99:99:99.99')
        self.assert_set_exception(TeledyneParameter2.TIME_PER_ENSEMBLE, '-1:-1:-1.+1')
        self.assert_set_exception(TeledyneParameter2.TIME_PER_ENSEMBLE, 3.1415926)

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.TIME_PER_ENSEMBLE, self._driver_parameter_defaults[TeledyneParameter.TIME_PER_ENSEMBLE])
        self.assert_set(TeledyneParameter2.TIME_PER_ENSEMBLE, self._driver_parameters[TeledyneParameter2.TIME_PER_ENSEMBLE][self.VALUE])
        self._tested[TeledyneParameter2.TIME_PER_ENSEMBLE] = True

    def _test_set_time_of_first_ping_readonly_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for TIME_OF_FIRST_PING ====== READONLY")

        # Test read only raise exceptions on set.        # TIME_OF_FIRST_PING:  -- str ****/**/**,**:**:** (CCYY/MM/DD,hh:mm:ss)
        now_1_hour = (dt.datetime.utcnow() + dt.timedelta(hours=1)).strftime("%Y/%m/%d,%H:%m:%S")
        today_plus_10 = (dt.datetime.utcnow() + dt.timedelta(days=10)).strftime("%Y/%m/%d,%H:%m:%S")
        today_plus_1month = (dt.datetime.utcnow() + dt.timedelta(days=31)).strftime("%Y/%m/%d,%H:%m:%S")
        today_plus_6month = (dt.datetime.utcnow() + dt.timedelta(days=183)).strftime("%Y/%m/%d,%H:%m:%S")

        self.assert_set_exception(TeledyneParameter2.TIME_OF_FIRST_PING, now_1_hour)
        self.assert_set_exception(TeledyneParameter2.TIME_OF_FIRST_PING, today_plus_10)
        self.assert_set_exception(TeledyneParameter2.TIME_OF_FIRST_PING, today_plus_1month)
        self.assert_set_exception(TeledyneParameter2.TIME_OF_FIRST_PING, today_plus_6month)
        self._tested[TeledyneParameter2.TIME_OF_FIRST_PING] = True

    def _test_set_time_per_ping_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for TIME_PER_PING ======")

        # TIME_PER_PING: '00:01.00'
        self.assert_set(TeledyneParameter2.TIME_PER_PING, '01:00.00')
        self.assert_set(TeledyneParameter2.TIME_PER_PING, '59:59.99')
        self.assert_set(TeledyneParameter2.TIME_PER_PING, '30:30.30')

        self.assert_set_exception(TeledyneParameter2.TIME_PER_PING, "LEROY JENKINS")
        self.assert_set_exception(TeledyneParameter2.TIME_PER_PING, 2)
        self.assert_set_exception(TeledyneParameter2.TIME_PER_PING, -1)
        self.assert_set_exception(TeledyneParameter2.TIME_PER_PING, '99:99.99')
        self.assert_set_exception(TeledyneParameter2.TIME_PER_PING, '-1:-1.+1')
        self.assert_set_exception(TeledyneParameter2.TIME_PER_PING, 3.1415926)

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.TIME_PER_PING, self._driver_parameter_defaults[TeledyneParameter.TIME_PER_PING])
        self.assert_set(TeledyneParameter2.TIME_PER_PING, self._driver_parameters[TeledyneParameter2.TIME_PER_PING][self.VALUE])
        self._tested[TeledyneParameter2.TIME_PER_PING] = True

    def _test_set_false_target_threshold_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for FALSE_TARGET_THRESHOLD ======")

        # FALSE_TARGET_THRESHOLD: string of 0-255,0-255
        self.assert_set(TeledyneParameter2.FALSE_TARGET_THRESHOLD, "000,000")
        self.assert_set(TeledyneParameter2.FALSE_TARGET_THRESHOLD, "255,000")
        self.assert_set(TeledyneParameter2.FALSE_TARGET_THRESHOLD, "000,255")
        self.assert_set(TeledyneParameter2.FALSE_TARGET_THRESHOLD, "255,255")

        self.assert_set_exception(TeledyneParameter2.FALSE_TARGET_THRESHOLD, "256,000")
        self.assert_set_exception(TeledyneParameter2.FALSE_TARGET_THRESHOLD, "256,255")
        self.assert_set_exception(TeledyneParameter2.FALSE_TARGET_THRESHOLD, "000,256")
        self.assert_set_exception(TeledyneParameter2.FALSE_TARGET_THRESHOLD, "255,256")
        self.assert_set_exception(TeledyneParameter2.FALSE_TARGET_THRESHOLD, -1)

        self.assert_set_exception(TeledyneParameter2.FALSE_TARGET_THRESHOLD, "LEROY JENKINS")

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.FALSE_TARGET_THRESHOLD, self._driver_parameter_defaults[TeledyneParameter.FALSE_TARGET_THRESHOLD])
        self.assert_set(TeledyneParameter2.FALSE_TARGET_THRESHOLD, self._driver_parameters[TeledyneParameter2.FALSE_TARGET_THRESHOLD][self.VALUE])
        self._tested[TeledyneParameter2.FALSE_TARGET_THRESHOLD] = True

    def _test_set_bandwidth_control_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for BANDWIDTH_CONTROL ======")

        # BANDWIDTH_CONTROL: 0/1,
        self.assert_set(TeledyneParameter2.BANDWIDTH_CONTROL, 1)

        self.assert_set_exception(TeledyneParameter2.BANDWIDTH_CONTROL, -1)
        self.assert_set_exception(TeledyneParameter2.BANDWIDTH_CONTROL, 2)
        self.assert_set_exception(TeledyneParameter2.BANDWIDTH_CONTROL, "LEROY JENKINS")
        self.assert_set_exception(TeledyneParameter2.BANDWIDTH_CONTROL, 3.1415926)

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.BANDWIDTH_CONTROL, self._driver_parameter_defaults[TeledyneParameter.BANDWIDTH_CONTROL])
        self.assert_set(TeledyneParameter2.BANDWIDTH_CONTROL, self._driver_parameters[TeledyneParameter2.BANDWIDTH_CONTROL][self.VALUE])
        self._tested[TeledyneParameter2.BANDWIDTH_CONTROL] = True

    def _test_set_correlation_threshold_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for CORRELATION_THRESHOLD ======")

        # CORRELATION_THRESHOLD: int 064, 0 - 255
        self.assert_set(TeledyneParameter2.CORRELATION_THRESHOLD, 50)
        self.assert_set(TeledyneParameter2.CORRELATION_THRESHOLD, 100)
        self.assert_set(TeledyneParameter2.CORRELATION_THRESHOLD, 150)
        self.assert_set(TeledyneParameter2.CORRELATION_THRESHOLD, 200)
        self.assert_set(TeledyneParameter2.CORRELATION_THRESHOLD, 255)

        self.assert_set_exception(TeledyneParameter2.CORRELATION_THRESHOLD, "LEROY JENKINS")
        self.assert_set_exception(TeledyneParameter2.CORRELATION_THRESHOLD, -256)
        self.assert_set_exception(TeledyneParameter2.CORRELATION_THRESHOLD, -1)
        self.assert_set_exception(TeledyneParameter2.CORRELATION_THRESHOLD, 3.1415926)

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.CORRELATION_THRESHOLD, self._driver_parameter_defaults[TeledyneParameter.CORRELATION_THRESHOLD])
        self.assert_set(TeledyneParameter2.CORRELATION_THRESHOLD, self._driver_parameters[TeledyneParameter2.CORRELATION_THRESHOLD][self.VALUE])
        self._tested[TeledyneParameter2.CORRELATION_THRESHOLD] = True

    def _test_set_error_velocity_threshold_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for ERROR_VELOCITY_THRESHOLD ======")

        # ERROR_VELOCITY_THRESHOLD: int (0-5000 mm/s) NOTE it enforces 0-9999
        # decimals are truncated to ints
        self.assert_set(TeledyneParameter2.ERROR_VELOCITY_THRESHOLD, 0)
        self.assert_set(TeledyneParameter2.ERROR_VELOCITY_THRESHOLD, 128)
        self.assert_set(TeledyneParameter2.ERROR_VELOCITY_THRESHOLD, 1000)
        self.assert_set(TeledyneParameter2.ERROR_VELOCITY_THRESHOLD, 2000)
        self.assert_set(TeledyneParameter2.ERROR_VELOCITY_THRESHOLD, 3000)
        self.assert_set(TeledyneParameter2.ERROR_VELOCITY_THRESHOLD, 4000)
        self.assert_set(TeledyneParameter2.ERROR_VELOCITY_THRESHOLD, 5000)

        self.assert_set_exception(TeledyneParameter2.ERROR_VELOCITY_THRESHOLD, "LEROY JENKINS")
        self.assert_set_exception(TeledyneParameter2.ERROR_VELOCITY_THRESHOLD, -1)
        self.assert_set_exception(TeledyneParameter2.ERROR_VELOCITY_THRESHOLD, 10000)
        self.assert_set_exception(TeledyneParameter2.ERROR_VELOCITY_THRESHOLD, -3.1415926)
        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.ERROR_VELOCITY_THRESHOLD, self._driver_parameter_defaults[TeledyneParameter.ERROR_VELOCITY_THRESHOLD])
        self.assert_set(TeledyneParameter2.ERROR_VELOCITY_THRESHOLD, self._driver_parameters[TeledyneParameter2.ERROR_VELOCITY_THRESHOLD][self.VALUE])
        self._tested[TeledyneParameter2.ERROR_VELOCITY_THRESHOLD] = True

    def _test_set_blank_after_transmit_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for BLANK_AFTER_TRANSMIT ======")

        # BLANK_AFTER_TRANSMIT: int 704, (0 - 9999)
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 0)
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 128)
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 1000)
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 2000)
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 3000)
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 4000)
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 5000)
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 6000)
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 7000)
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 8000)
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 9000)
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 9999)

        self.assert_set_exception(TeledyneParameter2.BLANK_AFTER_TRANSMIT, "LEROY JENKINS")
        self.assert_set_exception(TeledyneParameter2.BLANK_AFTER_TRANSMIT, -1)
        self.assert_set_exception(TeledyneParameter2.BLANK_AFTER_TRANSMIT, 10000)
        self.assert_set_exception(TeledyneParameter2.BLANK_AFTER_TRANSMIT, -3.1415926)
        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.BLANK_AFTER_TRANSMIT, self._driver_parameter_defaults[TeledyneParameter.BLANK_AFTER_TRANSMIT])
        self.assert_set(TeledyneParameter2.BLANK_AFTER_TRANSMIT, self._driver_parameters[TeledyneParameter2.BLANK_AFTER_TRANSMIT][self.VALUE])
        self._tested[TeledyneParameter2.BLANK_AFTER_TRANSMIT] = True

    def _test_set_clip_data_past_bottom_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for CLIP_DATA_PAST_BOTTOM ======")

        # CLIP_DATA_PAST_BOTTOM: True/False,
        self.assert_set(TeledyneParameter2.CLIP_DATA_PAST_BOTTOM, True)
        self.assert_set_exception(TeledyneParameter2.CLIP_DATA_PAST_BOTTOM, "LEROY JENKINS")

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.CLIP_DATA_PAST_BOTTOM, self._driver_parameter_defaults[TeledyneParameter.CLIP_DATA_PAST_BOTTOM])
        self.assert_set(TeledyneParameter2.CLIP_DATA_PAST_BOTTOM, self._driver_parameters[TeledyneParameter2.CLIP_DATA_PAST_BOTTOM][self.VALUE])
        self._tested[TeledyneParameter2.CLIP_DATA_PAST_BOTTOM] = True

    def _test_set_receiver_gain_select_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for RECEIVER_GAIN_SELECT ======")

        # RECEIVER_GAIN_SELECT: (0/1),
        self.assert_set(TeledyneParameter2.RECEIVER_GAIN_SELECT, 0)
        self.assert_set(TeledyneParameter2.RECEIVER_GAIN_SELECT, 1)

        self.assert_set_exception(TeledyneParameter2.RECEIVER_GAIN_SELECT, "LEROY JENKINS")
        self.assert_set_exception(TeledyneParameter2.RECEIVER_GAIN_SELECT, 2)
        self.assert_set_exception(TeledyneParameter2.RECEIVER_GAIN_SELECT, -1)
        self.assert_set_exception(TeledyneParameter2.RECEIVER_GAIN_SELECT, 3.1415926)

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.RECEIVER_GAIN_SELECT, self._driver_parameter_defaults[TeledyneParameter.RECEIVER_GAIN_SELECT])
        self.assert_set(TeledyneParameter2.RECEIVER_GAIN_SELECT, self._driver_parameters[TeledyneParameter2.RECEIVER_GAIN_SELECT][self.VALUE])
        self._tested[TeledyneParameter2.RECEIVER_GAIN_SELECT] = True

    def _test_set_receiver_gain_select_readonly_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for BLANK_AFTER_TRANSMIT ====== READONLY")

        # Test read only raise exceptions on set.
        self.assert_set_exception(TeledyneParameter2.RECEIVER_GAIN_SELECT, 0)
        self._tested[TeledyneParameter2.RECEIVER_GAIN_SELECT] = True

    def _test_set_number_of_depth_cells_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for NUMBER_OF_DEPTH_CELLS ======")

        # NUMBER_OF_DEPTH_CELLS:  -- int (1-255) 100,
        self.assert_set(TeledyneParameter2.NUMBER_OF_DEPTH_CELLS, 1)
        self.assert_set(TeledyneParameter2.NUMBER_OF_DEPTH_CELLS, 128)
        self.assert_set(TeledyneParameter2.NUMBER_OF_DEPTH_CELLS, 254)

        self.assert_set_exception(TeledyneParameter2.NUMBER_OF_DEPTH_CELLS, "LEROY JENKINS")
        self.assert_set_exception(TeledyneParameter2.NUMBER_OF_DEPTH_CELLS, 256)
        self.assert_set_exception(TeledyneParameter2.NUMBER_OF_DEPTH_CELLS, 0)
        self.assert_set_exception(TeledyneParameter2.NUMBER_OF_DEPTH_CELLS, -1)
        self.assert_set_exception(TeledyneParameter2.NUMBER_OF_DEPTH_CELLS, 3.1415926)

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.NUMBER_OF_DEPTH_CELLS, self._driver_parameter_defaults[TeledyneParameter.NUMBER_OF_DEPTH_CELLS])
        self.assert_set(TeledyneParameter2.NUMBER_OF_DEPTH_CELLS, self._driver_parameters[TeledyneParameter2.NUMBER_OF_DEPTH_CELLS][self.VALUE])
        self._tested[TeledyneParameter2.NUMBER_OF_DEPTH_CELLS] = True

    def _test_set_pings_per_ensemble_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for PINGS_PER_ENSEMBLE ======")

        # PINGS_PER_ENSEMBLE: -- int  (0-16384) 1,
        self.assert_set(TeledyneParameter2.PINGS_PER_ENSEMBLE, 0)
        self.assert_set(TeledyneParameter2.PINGS_PER_ENSEMBLE, 16384)

        self.assert_set_exception(TeledyneParameter2.PINGS_PER_ENSEMBLE, 16385)
        self.assert_set_exception(TeledyneParameter2.PINGS_PER_ENSEMBLE, -1)
        self.assert_set_exception(TeledyneParameter2.PINGS_PER_ENSEMBLE, 32767)
        self.assert_set_exception(TeledyneParameter2.PINGS_PER_ENSEMBLE, 3.1415926)
        self.assert_set_exception(TeledyneParameter2.PINGS_PER_ENSEMBLE, "LEROY JENKINS")
        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.PINGS_PER_ENSEMBLE, self._driver_parameter_defaults[TeledyneParameter.PINGS_PER_ENSEMBLE])
        self.assert_set(TeledyneParameter2.PINGS_PER_ENSEMBLE, self._driver_parameters[TeledyneParameter2.PINGS_PER_ENSEMBLE][self.VALUE])
        self._tested[TeledyneParameter2.PINGS_PER_ENSEMBLE] = True

    def _test_set_depth_cell_size_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for DEPTH_CELL_SIZE ======")

        # DEPTH_CELL_SIZE: int 80 - 3200
        self.assert_set(TeledyneParameter2.DEPTH_CELL_SIZE, 80)
        self.assert_set_exception(TeledyneParameter2.DEPTH_CELL_SIZE, 3200)

        self.assert_set_exception(TeledyneParameter2.DEPTH_CELL_SIZE, 3201)
        self.assert_set_exception(TeledyneParameter2.DEPTH_CELL_SIZE, -1)
        self.assert_set_exception(TeledyneParameter2.DEPTH_CELL_SIZE, 2)
        self.assert_set_exception(TeledyneParameter2.DEPTH_CELL_SIZE, 3.1415926)
        self.assert_set_exception(TeledyneParameter2.DEPTH_CELL_SIZE, "LEROY JENKINS")
        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.DEPTH_CELL_SIZE, self._driver_parameter_defaults[TeledyneParameter.DEPTH_CELL_SIZE])
        self.assert_set(TeledyneParameter2.DEPTH_CELL_SIZE, self._driver_parameters[TeledyneParameter2.DEPTH_CELL_SIZE][self.VALUE])
        self._tested[TeledyneParameter2.DEPTH_CELL_SIZE] = True

    def _test_set_transmit_length_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for TRANSMIT_LENGTH ======")

        # TRANSMIT_LENGTH: int 0 to 3200
        self.assert_set(TeledyneParameter2.TRANSMIT_LENGTH, 80)
        self.assert_set(TeledyneParameter2.TRANSMIT_LENGTH, 3200)

        self.assert_set_exception(TeledyneParameter2.TRANSMIT_LENGTH, 3201)
        self.assert_set_exception(TeledyneParameter2.TRANSMIT_LENGTH, -1)
        self.assert_set_exception(TeledyneParameter2.TRANSMIT_LENGTH, 3.1415926)
        self.assert_set_exception(TeledyneParameter2.TRANSMIT_LENGTH, "LEROY JENKINS")
        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.TRANSMIT_LENGTH, self._driver_parameter_defaults[TeledyneParameter.TRANSMIT_LENGTH])
        self.assert_set(TeledyneParameter2.TRANSMIT_LENGTH, self._driver_parameters[TeledyneParameter2.TRANSMIT_LENGTH][self.VALUE])
        self._tested[TeledyneParameter2.TRANSMIT_LENGTH] = True

    def _test_set_ping_weight_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for PING_WEIGHT ======")

        # PING_WEIGHT: (0/1),
        self.assert_set(TeledyneParameter2.PING_WEIGHT, 0)
        self.assert_set(TeledyneParameter2.PING_WEIGHT, 1)

        self.assert_set_exception(TeledyneParameter2.PING_WEIGHT, 2)
        self.assert_set_exception(TeledyneParameter2.PING_WEIGHT, -1)
        self.assert_set_exception(TeledyneParameter2.PING_WEIGHT, 3.1415926)
        self.assert_set_exception(TeledyneParameter2.PING_WEIGHT, "LEROY JENKINS")
        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.PING_WEIGHT, self._driver_parameter_defaults[TeledyneParameter.PING_WEIGHT])
        self.assert_set(TeledyneParameter2.PING_WEIGHT, self._driver_parameters[TeledyneParameter2.PING_WEIGHT][self.VALUE])
        self._tested[TeledyneParameter2.PING_WEIGHT] = True

    def _test_set_ambiguity_velocity_slave(self):
        ###
        #   test get set of a variety of parameter ranges
        ###
        log.debug("====== Testing ranges for AMBIGUITY_VELOCITY ======")

        # AMBIGUITY_VELOCITY: int 2 - 700
        self.assert_set(TeledyneParameter2.AMBIGUITY_VELOCITY, 2)
        self.assert_set(TeledyneParameter2.AMBIGUITY_VELOCITY, 111)
        self.assert_set(TeledyneParameter2.AMBIGUITY_VELOCITY, 222)
        self.assert_set(TeledyneParameter2.AMBIGUITY_VELOCITY, 333)
        self.assert_set(TeledyneParameter2.AMBIGUITY_VELOCITY, 444)
        self.assert_set(TeledyneParameter2.AMBIGUITY_VELOCITY, 555)
        self.assert_set(TeledyneParameter2.AMBIGUITY_VELOCITY, 666)
        self.assert_set(TeledyneParameter2.AMBIGUITY_VELOCITY, 700)

        self.assert_set_exception(TeledyneParameter2.AMBIGUITY_VELOCITY, 0)
        self.assert_set_exception(TeledyneParameter2.AMBIGUITY_VELOCITY, 1)
        self.assert_set_exception(TeledyneParameter2.AMBIGUITY_VELOCITY, -1)
        self.assert_set_exception(TeledyneParameter2.AMBIGUITY_VELOCITY, 3.1415926)
        self.assert_set_exception(TeledyneParameter2.AMBIGUITY_VELOCITY, "LEROY JENKINS")

        #
        # Reset to good value.
        #
        #self.assert_set(TeledyneParameter.AMBIGUITY_VELOCITY, self._driver_parameter_defaults[TeledyneParameter.AMBIGUITY_VELOCITY])
        self.assert_set(TeledyneParameter2.AMBIGUITY_VELOCITY, self._driver_parameters[TeledyneParameter2.AMBIGUITY_VELOCITY][self.VALUE])
        self._tested[TeledyneParameter2.AMBIGUITY_VELOCITY] = True

    def test_set_ranges_slave(self):
        self.assert_initialize_driver()


        self._test_set_xmit_power_slave()
        self._test_set_speed_of_sound_slave()
        self._test_set_pitch_slave()
        self._test_set_roll_slave()
        self._test_set_salinity_slave()
        self._test_set_sensor_source_slave()
        self._test_set_time_per_ensemble_slave()
        self._test_set_false_target_threshold_slave()
        self._test_set_bandwidth_control_slave()
        self._test_set_correlation_threshold_slave()
        self._test_set_error_velocity_threshold_slave()
        self._test_set_blank_after_transmit_slave()
        self._test_set_clip_data_past_bottom_slave()
        self._test_set_receiver_gain_select_slave()
        self._test_set_number_of_depth_cells_slave()
        self._test_set_pings_per_ensemble_slave()
        self._test_set_depth_cell_size_slave()
        self._test_set_transmit_length_slave()
        self._test_set_ping_weight_slave()
        self._test_set_ambiguity_velocity_slave()

        fail = False

        self.assertFalse(fail, "See above for un-exercized parameters.")



###############################################################################
#                            QUALIFICATION TESTS                              #
# Device specific qualification tests are for                                 #
# testing device specific capabilities                                        #
###############################################################################
@attr('QUAL', group='mi')
class QualFromIDK(WorkhorseDriverQualificationTest, ADCPTMixin):


    def setUp(self):
        InstrumentDriverQualificationTestCase.setUp(self)

    def init_port_agent(self):
        """
        @brief Launch the driver process and driver client.  This is used in the
        integration and qualification tests.  The port agent abstracts the physical
        interface with the instrument.
        @retval return the pid to the logger process
        """
        if self.port_agent:
            log.error("Port agent already initialized")
            return

        log.debug("Startup Port Agent")

        config = self.port_agent_config()
        log.debug("port agent config: %s", config)

        port_agents = {}

        if config['instrument_type'] != ConfigTypes.MULTI:
            config = {'only one port agent here!': config}
        for name, each in config.items():
            if type(each) != dict:
                continue
            port_agent_host = each.get('device_addr')
            if port_agent_host is not None:
                port_agent = PortAgentProcess.launch_process(each, timeout=60, test_mode=True)

                port = port_agent.get_data_port()
                pid = port_agent.get_pid()

                if port_agent_host == LOCALHOST:
                    log.info('Started port agent pid %s listening at port %s' % (pid, port))
                else:
                    log.info("Connecting to port agent on host: %s, port: %s", port_agent_host, port)
                port_agents[name] = port_agent

        self.addCleanup(self.stop_port_agent)
        self.port_agents = port_agents

    def stop_port_agent(self):
        """
        Stop the port agent.
        """
        log.info("Stop port agent")
        if self.port_agents:
            log.debug("found port agents, now stop them")
            for agent in self.port_agents.values():
                agent.stop()
        self.port_agents = {}

    def port_agent_comm_config(self):
        config = {}
        for name, each in self.port_agents.items():
            port = each.get_data_port()
            cmd_port = each.get_command_port()

            config[name] = {
                'addr': each._config['port_agent_addr'],
                'port': port,
                'cmd_port': cmd_port
            }
        return config

    def init_instrument_agent_client(self):
        log.info("Start Instrument Agent Client")

        # Driver config
        driver_config = {
            'dvr_mod': self.test_config.driver_module,
            'dvr_cls': self.test_config.driver_class,
            'workdir': self.test_config.working_dir,
            'process_type': (self.test_config.driver_process_type,),
            'comms_config': self.port_agent_comm_config(),
            'startup_config': self.test_config.driver_startup_config
        }

        # Create agent config.
        agent_config = {
            'driver_config': driver_config,
            'stream_config': self.data_subscribers.stream_config,
            'agent': {'resource_id': self.test_config.agent_resource_id},
            'test_mode': True  # Enable a poison pill. If the spawning process dies
            ## shutdown the daemon process.
        }

        log.debug("Agent Config: %s", agent_config)

        # Start instrument agent client.
        self.instrument_agent_manager.start_client(
            name=self.test_config.agent_name,
            module=self.test_config.agent_module,
            cls=self.test_config.agent_class,
            config=agent_config,
            resource_id=self.test_config.agent_resource_id,
            deploy_file=self.test_config.container_deploy_file
        )

        self.instrument_agent_client = self.instrument_agent_manager.instrument_agent_client

    def test_direct_access_telnet_mode_master(self):
        """
        @brief This test manually tests that the Instrument Driver properly supports direct access to the physical instrument. (telnet mode)
        """

        self.assert_enter_command_mode()
        self.assert_set_parameter(Parameter.SPEED_OF_SOUND, 1487)

        # go into direct access, and muck up a setting.
        self.assert_direct_access_start_telnet(timeout=600)

        self.tcp_client.send_data("%smaster::EC1488%s" % (NEWLINE, NEWLINE))

        self.tcp_client.expect(TeledynePrompt.COMMAND)

        self.assert_direct_access_stop_telnet()

        # verify the setting got restored.
        self.assert_enter_command_mode()
        # Direct access is true, it should be set before
        self.assert_get_parameter(Parameter.SPEED_OF_SOUND, 1487)

    def test_direct_access_telnet_mode_slave(self):
        """
        @brief This test manually tests that the Instrument Driver properly supports direct access to the physical instrument. (telnet mode)
        """

        self.assert_enter_command_mode()
        self.assert_set_parameter(Parameter.SPEED_OF_SOUND, 1487)

        # go into direct access, and muck up a setting.
        self.assert_direct_access_start_telnet(timeout=600)

        self.tcp_client.send_data("%sslave::EC1488%s" % (NEWLINE, NEWLINE))

        self.tcp_client.expect(TeledynePrompt.COMMAND)

        self.assert_direct_access_stop_telnet()

        # verify the setting got restored.
        self.assert_enter_command_mode()
        # Direct access is true, it should be set before
        self.assert_get_parameter(Parameter.SPEED_OF_SOUND, 1487)

    def test_recover_from_TG(self):
        """
        @brief This test manually tests that the Instrument Driver properly supports direct access to the physical instrument. (telnet mode)
        """

        self.assert_enter_command_mode()

        # go into direct access, and muck up a setting.
        self.assert_direct_access_start_telnet(timeout=600)
        today_plus_1month = (dt.datetime.utcnow() + dt.timedelta(days=31)).strftime("%Y/%m/%d,%H:%m:%S")

        self.tcp_client.send_data("%sTG%s%s" % (NEWLINE, today_plus_1month, NEWLINE))

        self.tcp_client.expect(Prompt.COMMAND)

        self.assert_direct_access_stop_telnet()

        # verify the setting got restored.
        self.assert_enter_command_mode()

        self.assert_get_parameter(Parameter.TIME_OF_FIRST_PING, '****/**/**,**:**:**')

    # Note: Parameter.COORDINATE_TRANSFORMATION is ReadOnly
    # Before testing it, remove the readOnly
    def _test_autosample_earth(self):

        #Verify autosample works and data particles are created
        #NOTE: If TG is set autosample behaves odd...

        self.assert_enter_command_mode()
        self.assert_set_parameter(Parameter.COORDINATE_TRANSFORMATION, '11111')
        self.assert_start_autosample()
        self.assert_particle_async(DataParticleType.ADCP_PD0_PARSED_EARTH, self.assert_particle_pd0_data_earth, timeout=140)

        self.assert_particle_polled(ProtocolEvent.GET_CALIBRATION, self.assert_compass_calibration, DataParticleType.ADCP_COMPASS_CALIBRATION, sample_count=1)
        self.assert_particle_polled(ProtocolEvent.GET_CONFIGURATION, self.assert_configuration, DataParticleType.ADCP_SYSTEM_CONFIGURATION, sample_count=1)
        self.assert_stop_autosample()

        self.assert_particle_polled(ProtocolEvent.GET_CALIBRATION, self.assert_compass_calibration, DataParticleType.ADCP_COMPASS_CALIBRATION, sample_count=1)
        self.assert_particle_polled(ProtocolEvent.GET_CONFIGURATION, self.assert_configuration, DataParticleType.ADCP_SYSTEM_CONFIGURATION, sample_count=1)

        # Restart autosample and gather a couple samples
        self.assert_sample_autosample(self.assert_particle_pd0_data_earth, DataParticleType.ADCP_PD0_PARSED_EARTH)


    # Note: Parameter.COORDINATE_TRANSFORMATION is ReadOnly
    # Before testin it, remove the readOnly
    def _test_autosample_beam(self):

        """
        Verify autosample works and data particles are created
        """
        self.assert_enter_command_mode()
        self.assert_set_parameter(Parameter.COORDINATE_TRANSFORMATION, '00111')
        self.assert_start_autosample()

        self.assert_particle_async(DataParticleType.ADCP_PD0_PARSED_BEAM, self.assert_particle_pd0_data, timeout=50) # ADCP_PD0_PARSED_BEAM
        self.assert_particle_polled(ProtocolEvent.GET_CALIBRATION, self.assert_compass_calibration, DataParticleType.ADCP_COMPASS_CALIBRATION, sample_count=1, timeout=20)

        self.assert_particle_polled(ProtocolEvent.GET_CONFIGURATION, self.assert_configuration, DataParticleType.ADCP_SYSTEM_CONFIGURATION, sample_count=1, timeout=20)

        # Stop autosample and do run a couple commands.
        self.assert_stop_autosample()

        self.assert_particle_polled(ProtocolEvent.GET_CALIBRATION, self.assert_compass_calibration, DataParticleType.ADCP_COMPASS_CALIBRATION, sample_count=1)
        self.assert_particle_polled(ProtocolEvent.GET_CONFIGURATION, self.assert_configuration, DataParticleType.ADCP_SYSTEM_CONFIGURATION, sample_count=1)

        # Restart autosample and gather a couple samples
        self.assert_sample_autosample(self.assert_particle_pd0_data, DataParticleType.ADCP_PD0_PARSED_BEAM)

    def assert_cycle(self):
        self.assert_start_autosample()

        self.assert_particle_async(DataParticleType.ADCP_PD0_PARSED_BEAM, self.assert_particle_pd0_data, timeout=200)
        self.assert_particle_polled(ProtocolEvent.GET_CALIBRATION, self.assert_compass_calibration, DataParticleType.ADCP_COMPASS_CALIBRATION, sample_count=1, timeout=20)
        self.assert_particle_polled(ProtocolEvent.GET_CONFIGURATION, self.assert_configuration, DataParticleType.ADCP_SYSTEM_CONFIGURATION, sample_count=1, timeout=20)

        # Stop autosample and do run a couple commands.
        self.assert_stop_autosample()

        self.assert_particle_polled(ProtocolEvent.GET_CALIBRATION, self.assert_compass_calibration, DataParticleType.ADCP_COMPASS_CALIBRATION, sample_count=1)
        self.assert_particle_polled(ProtocolEvent.GET_CONFIGURATION, self.assert_configuration, DataParticleType.ADCP_SYSTEM_CONFIGURATION, sample_count=1)

###############################################################################
#                             PUBLICATION TESTS                               #
# Device specific publication tests are for                                   #
# testing device specific capabilities                                        #
###############################################################################
@attr('PUB', group='mi')
class PubFromIDK(WorkhorseDriverPublicationTest):
    pass
