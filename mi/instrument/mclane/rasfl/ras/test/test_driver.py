"""
@package mi.instrument.mclane.ras.ooicore.test.test_driver
@file marine-integrations/mi/instrument/mclane/ras/ooicore/test/test_driver.py
@author Bill Bollenbacher
@brief Test cases for rasfl driver

USAGE:
 Make tests verbose and provide stdout
   * From the IDK
       $ bin/test_driver
       $ bin/test_driver -u [-t testname]
       $ bin/test_driver -i [-t testname]
       $ bin/test_driver -q [-t testname]
"""

__author__ = 'Bill Bollenbacher'
__license__ = 'Apache 2.0'

import unittest
import time

import gevent


# from interface.objects import AgentCapability
# from interface.objects import CapabilityType

# from nose.plugins.attrib import attr
from mock import Mock
from nose.plugins.attrib import attr

from mi.core.log import get_logger

log = get_logger()

# MI imports.
from mi.idk.unit_test import InstrumentDriverTestCase
from mi.idk.unit_test import InstrumentDriverUnitTestCase
from mi.idk.unit_test import InstrumentDriverIntegrationTestCase
from mi.idk.unit_test import InstrumentDriverQualificationTestCase
from mi.idk.unit_test import DriverTestMixin
from mi.idk.unit_test import ParameterTestConfigKey
from mi.idk.unit_test import AgentCapabilityType
# from mi.idk.unit_test import DriverStartupConfigKey

# from interface.objects import AgentCommand

# from mi.core.instrument.logger_client import LoggerClient

from mi.core.instrument.chunker import StringChunker
# from mi.core.instrument.instrument_driver import DriverAsyncEvent
# from mi.core.instrument.instrument_driver import DriverConnectionState
# from mi.core.instrument.instrument_driver import DriverParameter
from mi.core.instrument.instrument_driver import DriverEvent
# from mi.core.instrument.data_particle import DataParticleKey
# from mi.core.instrument.data_particle import DataParticleValue

from mi.instrument.mclane.rasfl.ras.driver import InstrumentDriver
from mi.instrument.mclane.rasfl.ras.driver import DataParticleType
from mi.instrument.mclane.rasfl.ras.driver import Command
from mi.instrument.mclane.rasfl.ras.driver import ProtocolState
from mi.instrument.mclane.rasfl.ras.driver import ProtocolEvent
from mi.instrument.mclane.rasfl.ras.driver import Capability
from mi.instrument.mclane.rasfl.ras.driver import Parameter
from mi.instrument.mclane.rasfl.ras.driver import Protocol
from mi.instrument.mclane.rasfl.ras.driver import Prompt
from mi.instrument.mclane.rasfl.ras.driver import NEWLINE
from mi.instrument.mclane.rasfl.ras.driver import RASFLSampleDataParticleKey
from mi.instrument.mclane.rasfl.ras.driver import RASFLSampleDataParticle

#from mi.core.exceptions import SampleException, InstrumentParameterException, InstrumentStateException
from mi.core.exceptions import SampleException
# from mi.core.exceptions import InstrumentProtocolException, InstrumentCommandException, Conflict
from interface.objects import AgentCommand

from ion.agents.instrument.direct_access.direct_access_server import DirectAccessTypes
from pyon.agent.agent import ResourceAgentEvent
from pyon.agent.agent import ResourceAgentState
# from mi.idk.exceptions import IDKException

# Globals
raw_stream_received = False
parsed_stream_received = False

###
#   Driver parameters for the tests
###
InstrumentDriverTestCase.initialize(
    driver_module='mi.instrument.mclane.rasfl.ras.driver',
    driver_class="InstrumentDriver",
    instrument_agent_resource_id='DQPJJX',
    instrument_agent_name='mclane_ras_ooicore',
    instrument_agent_packet_config=DataParticleType(),
    driver_startup_config={},
)


#################################### RULES ####################################
#                                                                             #
# Common capabilities in the base class                                       #
#                                                                             #
# Instrument specific stuff in the derived class                              #
#                                                                             #
# Generator spits out either stubs or comments describing test this here,     #
# test that there.                                                            #
#                                                                             #
# Qualification tests are driven through the instrument_agent                 #
#                                                                             #
###############################################################################

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
class UtilMixin(DriverTestMixin):
    """
    Mixin class used for storing data particle constants and common data assertion methods.
    """
    # Create some short names for the parameter test config
    TYPE = ParameterTestConfigKey.TYPE
    READONLY = ParameterTestConfigKey.READONLY
    STARTUP = ParameterTestConfigKey.STARTUP
    DA = ParameterTestConfigKey.DIRECT_ACCESS
    VALUE = ParameterTestConfigKey.VALUE
    REQUIRED = ParameterTestConfigKey.REQUIRED
    DEFAULT = ParameterTestConfigKey.DEFAULT
    STATES = ParameterTestConfigKey.STATES

    # battery voltage request response - TODO not implemented
    RASFL_BATTERY_DATA = "Battery: 29.9V [Alkaline, 18V minimum]" + NEWLINE

    # bag capacity response - TODO not implemented
    RASFL_CAPACITY_DATA = "Bag capacity: 500" + NEWLINE

    RASFL_VERSION_DATA = \
        "Version:" + NEWLINE + \
        NEWLINE + \
        "McLane Research Laboratories, Inc." + NEWLINE + \
        "CF2 Adaptive Remote Sampler" + NEWLINE + \
        "Version 3.02 of Jun  6 2013 15:38" + NEWLINE + \
        "Pump type: Maxon 125ml" + NEWLINE + \
        "Bag capacity: 500" + NEWLINE

    # response from collect sample meta command (from FORWARD or REVERSE command)
    RASFL_SAMPLE_DATA1 = "Status 00 |  75 100  25   4 |   1.5  90.7  .907*  1 031514 001727 | 29.9 0" + NEWLINE
    RASFL_SAMPLE_DATA2 = "Status 00 |  75 100  25   4 |   3.2 101.2 101.2*  2 031514 001728 | 29.9 0" + NEWLINE
    RASFL_SAMPLE_DATA3 = "Result 00 |  75 100  25   4 |  77.2  98.5  99.1  47 031514 001813 | 29.8 1" + NEWLINE

    _driver_capabilities = {
        # capabilities defined in the IOS
        Capability.CLOCK_SYNC: {STATES: [ProtocolState.COMMAND]},
    }

    ###
    # Parameter and Type Definitions
    ###
    _driver_parameters = {
        Parameter.FLUSH_VOLUME: {TYPE: int, READONLY: True, DA: False, STARTUP: True, VALUE: 150, REQUIRED: True},
        Parameter.FLUSH_FLOWRATE: {TYPE: int, READONLY: True, DA: False, STARTUP: True, VALUE: 100, REQUIRED: True},
        Parameter.FLUSH_MINFLOW: {TYPE: int, READONLY: True, DA: False, STARTUP: True, VALUE: 25, REQUIRED: True},
        Parameter.FILL_VOLUME: {TYPE: int, READONLY: True, DA: False, STARTUP: True, VALUE: 425, REQUIRED: True},
        Parameter.FILL_FLOWRATE: {TYPE: int, READONLY: True, DA: False, STARTUP: True, VALUE: 75, REQUIRED: True},
        Parameter.FILL_MINFLOW: {TYPE: int, READONLY: True, DA: False, STARTUP: True, VALUE: 25, REQUIRED: True},
        Parameter.REVERSE_VOLUME: {TYPE: int, READONLY: True, DA: False, STARTUP: True, VALUE: 75, REQUIRED: True},
        Parameter.REVERSE_FLOWRATE: {TYPE: int, READONLY: True, DA: False, STARTUP: True, VALUE: 100, REQUIRED: True},
        Parameter.REVERSE_MINFLOW: {TYPE: int, READONLY: True, DA: False, STARTUP: True, VALUE: 25, REQUIRED: True}}

    ###
    # Data Particle Parameters
    ### 
    _sample_parameters = {
        # particle data defined in the OPTAA Driver doc
        RASFLSampleDataParticleKey.PORT: {'type': int, 'value': 0},
        RASFLSampleDataParticleKey.VOLUME_COMMANDED: {'type': int, 'value': 75},
        RASFLSampleDataParticleKey.FLOW_RATE_COMMANDED: {'type': int, 'value': 100},
        RASFLSampleDataParticleKey.MIN_FLOW_COMMANDED: {'type': int, 'value': 25},
        RASFLSampleDataParticleKey.TIME_LIMIT: {'type': int, 'value': 4},
        RASFLSampleDataParticleKey.VOLUME_ACTUAL: {'type': float, 'value': 1.5},
        RASFLSampleDataParticleKey.FLOW_RATE_ACTUAL: {'type': float, 'value': 90.7},
        RASFLSampleDataParticleKey.MIN_FLOW_ACTUAL: {'type': float, 'value': 0.907},
        RASFLSampleDataParticleKey.TIMER: {'type': int, 'value': 1},
        RASFLSampleDataParticleKey.DATE: {'type': unicode, 'value': '031514'},
        RASFLSampleDataParticleKey.TIME: {'type': unicode, 'value': '001727'},
        RASFLSampleDataParticleKey.BATTERY: {'type': float, 'value': 29.9},
        RASFLSampleDataParticleKey.CODE: {'type': int, 'value': 0},
    }

    ###
    # Driver Parameter Methods
    ###
    def assert_driver_parameters(self, current_parameters, verify_values=False):
        """
        Verify that all driver parameters are correct and potentially verify values.
        @param current_parameters: driver parameters read from the driver instance
        @param verify_values: should we verify values against definition?
        """
        self.assert_parameters(current_parameters, self._driver_parameters, verify_values)

    ###
    # Data Particle Parameters Methods
    ### 
    def assert_data_particle_sample(self, data_particle, verify_values=False):
        """
        Verify an optaa sample data particle
        @param data_particle: OPTAAA_SampleDataParticle data particle
        @param verify_values: bool, should we verify parameter values
        """
        #self.assert_data_particle_header(data_particle, DataParticleType.METBK_PARSED)
        self.assert_data_particle_parameters(data_particle, self._sample_parameters, verify_values)

    def assert_data_particle_status(self, data_particle, verify_values=False):
        """
        Verify an optaa status data particle
        @param data_particle: OPTAAA_StatusDataParticle data particle
        @param verify_values: bool, should we verify parameter values
        """
        # TODO - what are we attempting to test here?
        # self.assert_data_particle_header(data_particle, DataParticleType.RASFL_STATUS)
        # self.assert_data_particle_parameters(data_particle, self._status_parameters, verify_values)

        # TODO - assert_particle_published is not implemented - is it necessary?
        # def assert_particle_not_published(self, driver, sample_data, particle_assert_method, verify_values=False):
        #     try:
        #         self.assert_particle_published(driver, sample_data, particle_assert_method, verify_values)
        #     except AssertionError as e:
        #         if str(e) == "0 != 1":
        #             return
        #         else:
        #             raise e
        #     else:
        #         raise IDKException("assert_particle_not_published: particle was published")


###############################################################################
#                                UNIT TESTS                                   #
#         Unit tests test the method calls and parameters using Mock.         #
#                                                                             #
#   These tests are especially useful for testing parsers and other data      #
#   handling.  The tests generally focus on small segments of code, like a    #
#   single function call, but more complex code using Mock objects.  However  #
#   if you find yourself mocking too much maybe it is better as an            #
#   integration test.                                                         #
#                                                                             #
#   Unit tests do not start up external processes like the port agent or      #
#   driver process.                                                           #
###############################################################################
@attr('UNIT', group='mi')
class TestUNIT(InstrumentDriverUnitTestCase, UtilMixin):
    def setUp(self):
        InstrumentDriverUnitTestCase.setUp(self)

    print '----- unit test -----'

    #@unittest.skip('not completed yet')
    def test_driver_enums(self):
        """
        Verify that all driver enumeration has no duplicate values that might cause confusion.  Also
        do a little extra validation for the Capabilites
        """

        self.assert_enum_has_no_duplicates(DataParticleType())
        self.assert_enum_has_no_duplicates(ProtocolState())
        self.assert_enum_has_no_duplicates(ProtocolEvent())
        self.assert_enum_has_no_duplicates(Parameter())
        self.assert_enum_has_no_duplicates(Command())

        # Test capabilities for duplicates, then verify that capabilities is a subset of protocol events
        self.assert_enum_has_no_duplicates(Capability())
        self.assert_enum_complete(Capability(), ProtocolEvent())

    def test_chunker(self):
        """
        Test the chunker and verify the particles created.
        """
        chunker = StringChunker(Protocol.sieve_function)

        self.assert_chunker_sample(chunker, self.RASFL_SAMPLE_DATA1)
        self.assert_chunker_sample_with_noise(chunker, self.RASFL_SAMPLE_DATA1)
        self.assert_chunker_fragmented_sample(chunker, self.RASFL_SAMPLE_DATA1)
        self.assert_chunker_combined_sample(chunker, self.RASFL_SAMPLE_DATA1)

        self.assert_chunker_sample(chunker, self.RASFL_SAMPLE_DATA2)
        self.assert_chunker_sample_with_noise(chunker, self.RASFL_SAMPLE_DATA2)
        self.assert_chunker_fragmented_sample(chunker, self.RASFL_SAMPLE_DATA2)
        self.assert_chunker_combined_sample(chunker, self.RASFL_SAMPLE_DATA2)

        self.assert_chunker_sample(chunker, self.RASFL_SAMPLE_DATA3)
        self.assert_chunker_sample_with_noise(chunker, self.RASFL_SAMPLE_DATA3)
        self.assert_chunker_fragmented_sample(chunker, self.RASFL_SAMPLE_DATA3)
        self.assert_chunker_combined_sample(chunker, self.RASFL_SAMPLE_DATA3)

    def test_corrupt_data_sample(self):
        # garbage is not okay
        particle = RASFLSampleDataParticle(self.RASFL_SAMPLE_DATA1.replace('00', 'foo'),
                                           port_timestamp=3558720820.531179)
        with self.assertRaises(SampleException):
            particle.generate()

    def test_got_data(self):
        """
        Verify sample data passed through the got data method produces the correct data particles
        """
        # Create and initialize the instrument driver with a mock port agent
        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_initialize_driver(driver)

        self.assert_raw_particle_published(driver, True)

        # validating data particles are published
        self.assert_particle_published(driver, self.RASFL_SAMPLE_DATA1, self.assert_data_particle_sample, True)

        # validate that a duplicate sample is not published - TODO
        #self.assert_particle_not_published(driver, self.RASFL_SAMPLE_DATA1, self.assert_data_particle_sample, True)

        # validate that a new sample is published
        self.assert_particle_published(driver, self.RASFL_SAMPLE_DATA2, self.assert_data_particle_sample, False)

    def test_protocol_filter_capabilities(self):
        """
        This tests driver filter_capabilities.
        Iterate through available capabilities, and verify that they can pass successfully through the filter.
        Test silly made up capabilities to verify they are blocked by filter.
        """
        mock_callback = Mock(spec="UNKNOWN WHAT SHOULD GO HERE FOR evt_callback")
        protocol = Protocol(Prompt, NEWLINE, mock_callback)
        driver_capabilities = Capability().list()
        test_capabilities = Capability().list()

        # Add a bogus capability that will be filtered out.
        test_capabilities.append("BOGUS_CAPABILITY")

        # Verify "BOGUS_CAPABILITY was filtered out
        self.assertEquals(sorted(driver_capabilities),
                          sorted(protocol._filter_capabilities(test_capabilities)))

    def test_capabilities(self):
        """
        Verify the FSM reports capabilities as expected.  All states defined in this dict must
        also be defined in the protocol FSM.
        """
        capabilities = {
            ProtocolState.UNKNOWN: [
                ProtocolEvent.DISCOVER,
            ],
            ProtocolState.COMMAND: [
                ProtocolEvent.GET,
                ProtocolEvent.SET,
                ProtocolEvent.START_DIRECT,
                ProtocolEvent.ACQUIRE_SAMPLE,
                ProtocolEvent.CLOCK_SYNC,
            ],
            ProtocolState.ACQUIRE_SAMPLE: [
                ProtocolEvent.ACQUIRE_SAMPLE,
            ],
            ProtocolState.DIRECT_ACCESS: [
                ProtocolEvent.STOP_DIRECT,
                ProtocolEvent.EXECUTE_DIRECT,
            ],
        }

        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_capabilities(driver, capabilities)

    #@unittest.skip('not completed yet')
    def test_driver_schema(self):
        """
        get the driver schema and verify it is configured properly
        """
        driver = InstrumentDriver(self._got_data_event_callback)
        self.assert_driver_schema(driver, self._driver_parameters, self._driver_capabilities)


###############################################################################
#                            INTEGRATION TESTS                                #
#     Integration test test the direct driver / instrument interaction        #
#     but making direct calls via zeromq.                                     #
#     - Common Integration tests test the driver through the instrument agent #
#     and common for all drivers (minimum requirement for ION ingestion)      #
###############################################################################
@attr('INT', group='mi')
class TestINT(InstrumentDriverIntegrationTestCase, UtilMixin):
    def setUp(self):
        InstrumentDriverIntegrationTestCase.setUp(self)

    def assert_async_particle_not_generated(self, particle_type, timeout=10):
        end_time = time.time() + timeout

        while end_time > time.time():
            if len(self.get_sample_events(particle_type)) > 0:
                self.fail("assert_async_particle_not_generated: a particle of type %s was published" % particle_type)
            time.sleep(.3)

    def test_parameters(self):
        """
        Test driver parameters and verify their type.  Startup parameters also verify the parameter
        value.  This test confirms that parameters are being read/converted properly and that
        the startup has been applied.
        """
        self.assert_initialize_driver()
        reply = self.driver_client.cmd_dvr('get_resource', Parameter.ALL)
        log.debug('Startup parameters: %s', reply)
        self.assert_driver_parameters(reply)

    def test_execute_clock_sync_command_mode(self):
        """
        Verify we can synchronize the instrument internal clock in command mode
        """
        self.assert_initialize_driver(ProtocolState.COMMAND)

        # compare instrument prompt time (after processing clock sync) with current system time
        reply = self.driver_client.cmd_dvr('execute_resource', ProtocolEvent.CLOCK_SYNC)
        gmt_time = time.gmtime()  # the most recent instrument time (from command prompt)
        ras_time = reply[1]
        diff = abs(time.mktime(ras_time) - time.mktime(gmt_time))
        log.info('clock synchronized within %f seconds', diff)

        # Verify that the time matches to within 5 seconds
        self.assertLessEqual(diff, 5)

    def test_acquire_sample(self):
        """
        Test that we can generate sample particle with command
        """
        self.assert_initialize_driver()
        self.driver_client.cmd_dvr('execute_resource', ProtocolEvent.ACQUIRE_SAMPLE)
        self.assert_state_change(ProtocolState.COMMAND, 1)
        self.assert_particle_generation(ProtocolEvent.ACQUIRE_SAMPLE, DataParticleType.RASFL_PARSED,
                                        self.assert_data_particle_sample)


################################################################################
#                            QUALIFICATION TESTS                               #
# Device specific qualification tests are for doing final testing of ion       #
# integration.  They generally aren't used for instrument debugging and should #
# be tackled after all unit and integration tests are complete                 #
################################################################################
@attr('QUAL', group='mi')
class TestQUAL(InstrumentDriverQualificationTestCase, UtilMixin):
    def setUp(self):
        InstrumentDriverQualificationTestCase.setUp(self)

    def assert_sample_polled(self, sample_data_assert, sample_queue, timeout=10):
        """
        Test observatory polling function.

        Verifies the acquire_status command.
        """
        # Set up all data subscriptions.  Stream names are defined
        # in the driver PACKET_CONFIG dictionary
        self.data_subscribers.start_data_subscribers()
        self.addCleanup(self.data_subscribers.stop_data_subscribers)

        self.assert_enter_command_mode()

        ###
        # Poll for a sample
        ###

        # make sure there aren't any junk samples in the parsed
        # data queue.
        log.debug("Acquire Sample")
        self.data_subscribers.clear_sample_queue(sample_queue)

        cmd = AgentCommand(command=DriverEvent.ACQUIRE_SAMPLE)
        self.instrument_agent_client.execute_resource(cmd, timeout=timeout)

        # Watch the parsed data queue and return once a sample
        # has been read or the default timeout has been reached.
        samples = self.data_subscribers.get_samples(sample_queue, 1, timeout=timeout)
        self.assertGreaterEqual(len(samples), 1)
        log.error("SAMPLE: %s" % samples)

        # Verify
        for sample in samples:
            sample_data_assert(sample)

        self.assert_reset()
        self.doCleanups()

    # RASFL does not poll or autosample
    # def test_poll(self):
    #     """
    #     poll for a single sample
    #     """
    #     #self.assert_sample_polled(self.assert_data_particle_sample,
    #     #                          DataParticleType.METBK_PARSED)
    #
    # def test_autosample(self):
    #     """
    #     start and stop autosample and verify data particle
    #     """
    #     #self.assert_sample_autosample(self.assert_data_particle_sample,
    #     #                              DataParticleType.METBK_PARSED,
    #     #                              sample_count=1,
    #     #                              timeout=60)

    # TODO - not sure how this will work - wake up command, Ctrl-C, cannot be sent over a manual telnet session
    def test_direct_access_telnet_mode(self):
        """
        @brief This test automatically tests that the Instrument Driver properly supports direct access to the physical instrument. (telnet mode)
        """
        self.assert_enter_command_mode()

        # go into direct access
        self.assert_direct_access_start_telnet(timeout=600)
        self.tcp_client.send_data("#D\r\n")
        if not self.tcp_client.expect("\r\n"):
            self.fail("test_direct_access_telnet_mode: did not get expected response")

        self.assert_direct_access_stop_telnet()

    @unittest.skip('Only enabled and used for manual testing of vendor SW')
    def test_direct_access_telnet_mode_manual(self):
        """
        @brief This test manually tests that the Instrument Driver properly supports direct access to the physical instrument. (virtual serial port mode)
        """
        self.assert_enter_command_mode()

        # go direct access
        cmd = AgentCommand(command=ResourceAgentEvent.GO_DIRECT_ACCESS,
                           kwargs={'session_type': DirectAccessTypes.vsp,
                                   'session_timeout': 600,
                                   'inactivity_timeout': 600})
        retval = self.instrument_agent_client.execute_agent(cmd, timeout=600)
        log.warn("go_direct_access retval=" + str(retval.result))

        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.DIRECT_ACCESS)

        print("test_direct_access_telnet_mode: waiting 120 seconds for manual testing")
        gevent.sleep(120)

        cmd = AgentCommand(command=ResourceAgentEvent.GO_COMMAND)
        self.instrument_agent_client.execute_agent(cmd)

        state = self.instrument_agent_client.get_agent_state()
        self.assertEqual(state, ResourceAgentState.COMMAND)

    def test_discover(self):
        """
        over-ridden because instrument doesn't actually have an autosample mode and therefore
        driver will always go to command mode during the discover process after a reset.
        """
        # Verify the agent is in command mode
        self.assert_enter_command_mode()

        self.assert_start_autosample()

        # Now reset and try to discover.  This will stop the driver and cause it to re-discover which
        # will always go back to command for this instrument
        self.assert_reset()
        self.assert_discover(ResourceAgentState.COMMAND)


    def test_get_capabilities(self):
        """
        @brief Walk through all driver protocol states and verify capabilities
        returned by get_current_capabilities
        """
        self.assert_enter_command_mode()

        ##################
        #  Command Mode
        ##################

        capabilities = {
            AgentCapabilityType.AGENT_COMMAND: self._common_agent_commands(ResourceAgentState.COMMAND),
            AgentCapabilityType.AGENT_PARAMETER: self._common_agent_parameters(),
            AgentCapabilityType.RESOURCE_COMMAND: [
                ProtocolEvent.GET,
                ProtocolEvent.CLOCK_SYNC,
                ProtocolEvent.ACQUIRE_SAMPLE,
            ],
            AgentCapabilityType.RESOURCE_INTERFACE: None,
            AgentCapabilityType.RESOURCE_PARAMETER: self._driver_parameters.keys()
        }

        self.assert_capabilities(capabilities)

        ##################
        #  Streaming Mode
        ##################

        capabilities[AgentCapabilityType.AGENT_COMMAND] = self._common_agent_commands(ResourceAgentState.STREAMING)
        capabilities[AgentCapabilityType.RESOURCE_COMMAND] = [
            ProtocolEvent.GET,
            ProtocolEvent.CLOCK_SYNC,
            ProtocolEvent.ACQUIRE_SAMPLE,
        ]

        self.assert_start_autosample()
        self.assert_capabilities(capabilities)
        self.assert_stop_autosample()

        ##################
        #  DA Mode
        ##################

        capabilities[AgentCapabilityType.AGENT_COMMAND] = self._common_agent_commands(ResourceAgentState.DIRECT_ACCESS)
        capabilities[AgentCapabilityType.RESOURCE_COMMAND] = self._common_da_resource_commands()

        self.assert_direct_access_start_telnet()
        self.assert_capabilities(capabilities)
        self.assert_direct_access_stop_telnet()

        #######################
        #  Uninitialized Mode
        #######################

        capabilities[AgentCapabilityType.AGENT_COMMAND] = self._common_agent_commands(ResourceAgentState.UNINITIALIZED)
        capabilities[AgentCapabilityType.RESOURCE_COMMAND] = []
        capabilities[AgentCapabilityType.RESOURCE_INTERFACE] = []
        capabilities[AgentCapabilityType.RESOURCE_PARAMETER] = []

        self.assert_reset()
        self.assert_capabilities(capabilities)

    def test_execute_clock_sync(self):
        """
        Verify we can synchronize the instrument internal clock
        """
        self.assert_enter_command_mode()

        self.assert_execute_resource(ProtocolEvent.CLOCK_SYNC)

        # get the time from the driver
        check_new_params = self.instrument_agent_client.get_resource([Parameter.CLOCK])
        # convert driver's time from formatted date/time string to seconds integer
        instrument_time = time.mktime(
            time.strptime(check_new_params.get(Parameter.CLOCK).lower(), "%Y/%m/%d  %H:%M:%S"))

        # need to convert local machine's time to date/time string and back to seconds to 'drop' the DST attribute so test passes
        # get time from local machine
        lt = time.strftime("%d %b %Y %H:%M:%S", time.gmtime(time.mktime(time.localtime())))
        # convert local time from formatted date/time string to seconds integer to drop DST
        local_time = time.mktime(time.strptime(lt, "%d %b %Y %H:%M:%S"))

        # Now verify that the time matches to within 5 seconds
        self.assertLessEqual(abs(instrument_time - local_time), 5)

    @unittest.skip("doesn't pass because IA doesn't apply the startup parameters yet")
    def test_get_parameters(self):
        """
        verify that parameters can be gotten properly
        """
        self.assert_enter_command_mode()

        reply = self.instrument_agent_client.get_resource(Parameter.ALL)
        self.assert_driver_parameters(reply)
