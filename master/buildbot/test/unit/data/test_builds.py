# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members


from unittest import mock

from twisted.internet import defer
from twisted.trial import unittest

from buildbot.data import builds
from buildbot.data import resultspec
from buildbot.test import fakedb
from buildbot.test.fake import fakemaster
from buildbot.test.reactor import TestReactorMixin
from buildbot.test.util import endpoint
from buildbot.test.util import interfaces
from buildbot.util import epoch2datetime


class BuildEndpoint(endpoint.EndpointMixin, unittest.TestCase):
    endpointClass = builds.BuildEndpoint
    resourceTypeClass = builds.Build

    @defer.inlineCallbacks
    def setUp(self):
        yield self.setUpEndpoint()
        yield self.master.db.insert_test_data([
            fakedb.Builder(id=77, name='builder77'),
            fakedb.Master(id=88),
            fakedb.Worker(id=13, name='wrk'),
            fakedb.Buildset(id=8822),
            fakedb.BuildRequest(id=82, buildsetid=8822, builderid=77),
            fakedb.Build(
                id=13, builderid=77, masterid=88, workerid=13, buildrequestid=82, number=3
            ),
            fakedb.Build(
                id=14, builderid=77, masterid=88, workerid=13, buildrequestid=82, number=4
            ),
            fakedb.Build(
                id=15, builderid=77, masterid=88, workerid=13, buildrequestid=82, number=5
            ),
            fakedb.BuildProperty(
                buildid=13, name='reason', value='"force build"', source="Force Build Form"
            ),
        ])

    @defer.inlineCallbacks
    def test_get_existing(self):
        build = yield self.callGet(('builds', 14))
        self.validateData(build)
        self.assertEqual(build['number'], 4)

    @defer.inlineCallbacks
    def test_get_missing(self):
        build = yield self.callGet(('builds', 9999))
        self.assertEqual(build, None)

    @defer.inlineCallbacks
    def test_get_missing_builder_number(self):
        build = yield self.callGet(('builders', 999, 'builds', 4))
        self.assertEqual(build, None)

    @defer.inlineCallbacks
    def test_get_builder_missing_number(self):
        build = yield self.callGet(('builders', 77, 'builds', 44))
        self.assertEqual(build, None)

    @defer.inlineCallbacks
    def test_get_builder_number(self):
        build = yield self.callGet(('builders', 77, 'builds', 5))
        self.validateData(build)
        self.assertEqual(build['buildid'], 15)

    @defer.inlineCallbacks
    def test_get_buildername_number(self):
        build = yield self.callGet(('builders', 'builder77', 'builds', 5))
        self.validateData(build)
        self.assertEqual(build['buildid'], 15)

    @defer.inlineCallbacks
    def test_get_buildername_not_existing_number(self):
        build = yield self.callGet(('builders', 'builder77_nope', 'builds', 5))
        self.assertEqual(build, None)

    @defer.inlineCallbacks
    def test_properties_injection(self):
        resultSpec = resultspec.OptimisedResultSpec(
            properties=[resultspec.Property(b'property', 'eq', ['reason'])]
        )
        build = yield self.callGet(('builders', 77, 'builds', 3), resultSpec=resultSpec)
        self.validateData(build)
        self.assertIn('reason', build['properties'])

    @defer.inlineCallbacks
    def test_action_stop(self):
        yield self.callControl("stop", {}, ('builders', 77, 'builds', 5))
        self.master.mq.assertProductions([
            (('control', 'builds', '15', 'stop'), {'reason': 'no reason'})
        ])

    @defer.inlineCallbacks
    def test_action_stop_reason(self):
        yield self.callControl("stop", {'reason': 'because'}, ('builders', 77, 'builds', 5))
        self.master.mq.assertProductions([
            (('control', 'builds', '15', 'stop'), {'reason': 'because'})
        ])

    @defer.inlineCallbacks
    def test_action_rebuild(self):
        self.patch(
            self.master.data.updates,
            "rebuildBuildrequest",
            mock.Mock(spec=self.master.data.updates.rebuildBuildrequest, return_value=(1, [2])),
        )
        r = yield self.callControl("rebuild", {}, ('builders', 77, 'builds', 5))
        self.assertEqual(r, (1, [2]))

        buildrequest = yield self.master.data.get(('buildrequests', 82))
        self.master.data.updates.rebuildBuildrequest.assert_called_with(buildrequest)


class BuildTriggeredBuildsEndpoint(endpoint.EndpointMixin, unittest.TestCase):
    endpointClass = builds.BuildTriggeredBuildsEndpoint
    resourceTypeClass = builds.Build

    @defer.inlineCallbacks
    def setUp(self):
        yield self.setUpEndpoint()
        yield self.master.db.insert_test_data([
            fakedb.Master(id=88),
            fakedb.Buildset(id=20),
            fakedb.Builder(id=77, name="b1"),
            fakedb.BuildRequest(id=40, buildsetid=20, builderid=77),
            fakedb.BuildRequest(id=41, buildsetid=20, builderid=77),
            fakedb.Worker(id=13, name='wrk'),
            fakedb.Build(id=50, buildrequestid=41, masterid=88, builderid=77, workerid=13),
            fakedb.Build(id=51, buildrequestid=40, masterid=88, builderid=77, workerid=13),
            fakedb.Buildset(id=1000, parent_buildid=51),
            fakedb.BuildRequest(id=1100, buildsetid=1000, builderid=77),
            fakedb.BuildRequest(id=1101, buildsetid=1000, builderid=77),
            fakedb.Build(id=1200, buildrequestid=1100, masterid=88, builderid=77, workerid=13),
            fakedb.Build(id=1201, buildrequestid=1101, masterid=88, builderid=77, workerid=13),
            fakedb.Buildset(id=1001, parent_buildid=51),
            fakedb.BuildRequest(id=1110, buildsetid=1001, builderid=77),
            fakedb.BuildRequest(id=1111, buildsetid=1001, builderid=77),
            fakedb.Build(id=1210, buildrequestid=1110, masterid=88, builderid=77, workerid=13),
            fakedb.Build(id=1211, buildrequestid=1111, masterid=88, builderid=77, workerid=13),
        ])

    @defer.inlineCallbacks
    def test_get_not_existing(self):
        builds = yield self.callGet(('builds', 50, 'triggered_builds'))
        self.assertEqual(builds, [])

    @defer.inlineCallbacks
    def test_get(self):
        builds = yield self.callGet(('builds', 51, 'triggered_builds'))

        for build in builds:
            self.validateData(build)

        self.assertEqual(sorted([b['buildid'] for b in builds]), [1200, 1201, 1210, 1211])


class BuildsEndpoint(endpoint.EndpointMixin, unittest.TestCase):
    endpointClass = builds.BuildsEndpoint
    resourceTypeClass = builds.Build

    @defer.inlineCallbacks
    def setUp(self):
        yield self.setUpEndpoint()
        yield self.master.db.insert_test_data([
            fakedb.Builder(id=77, name='builder77'),
            fakedb.Builder(id=78, name='builder78'),
            fakedb.Builder(id=79, name='builder79'),
            fakedb.Master(id=88),
            fakedb.Worker(id=12, name='wrk'),
            fakedb.Worker(id=13, name='wrk2'),
            fakedb.Buildset(id=8822),
            fakedb.BuildRequest(id=82, builderid=77, buildsetid=8822),
            fakedb.BuildRequest(id=83, builderid=77, buildsetid=8822),
            fakedb.BuildRequest(id=84, builderid=77, buildsetid=8822),
            fakedb.Build(
                id=13, builderid=77, masterid=88, workerid=13, buildrequestid=82, number=3
            ),
            fakedb.Build(
                id=14, builderid=77, masterid=88, workerid=13, buildrequestid=82, number=4
            ),
            fakedb.Build(
                id=15,
                builderid=78,
                masterid=88,
                workerid=12,
                buildrequestid=83,
                number=5,
                complete_at=1,
            ),
            fakedb.Build(
                id=16,
                builderid=79,
                masterid=88,
                workerid=12,
                buildrequestid=84,
                number=6,
                complete_at=1,
            ),
            fakedb.BuildProperty(
                buildid=13, name='reason', value='"force build"', source="Force Build Form"
            ),
        ])

    @defer.inlineCallbacks
    def test_get_all(self):
        builds = yield self.callGet(('builds',))

        for build in builds:
            self.validateData(build)

        self.assertEqual(sorted([b['number'] for b in builds]), [3, 4, 5, 6])

    @defer.inlineCallbacks
    def test_get_builder(self):
        builds = yield self.callGet(('builders', 78, 'builds'))

        for build in builds:
            self.validateData(build)

        self.assertEqual(sorted([b['number'] for b in builds]), [5])

    @defer.inlineCallbacks
    def test_get_buildername(self):
        builds = yield self.callGet(('builders', 'builder78', 'builds'))

        for build in builds:
            self.validateData(build)

        self.assertEqual(sorted([b['number'] for b in builds]), [5])

    @defer.inlineCallbacks
    def test_get_buildername_not_existing(self):
        builds = yield self.callGet(('builders', 'builder78_nope', 'builds'))
        self.assertEqual(builds, [])

    @defer.inlineCallbacks
    def test_get_buildrequest(self):
        builds = yield self.callGet(('buildrequests', 82, 'builds'))

        for build in builds:
            self.validateData(build)

        self.assertEqual(sorted([b['number'] for b in builds]), [3, 4])

    @defer.inlineCallbacks
    def test_get_buildrequest_not_existing(self):
        builds = yield self.callGet(('buildrequests', 899, 'builds'))
        self.assertEqual(builds, [])

    @defer.inlineCallbacks
    def test_get_buildrequest_via_filter(self):
        resultSpec = resultspec.OptimisedResultSpec(
            filters=[resultspec.Filter('buildrequestid', 'eq', [82])]
        )
        builds = yield self.callGet(('builds',), resultSpec=resultSpec)

        for build in builds:
            self.validateData(build)

        self.assertEqual(sorted([b['number'] for b in builds]), [3, 4])

    @defer.inlineCallbacks
    def test_get_buildrequest_via_filter_with_string(self):
        resultSpec = resultspec.OptimisedResultSpec(
            filters=[resultspec.Filter('buildrequestid', 'eq', ['82'])]
        )
        builds = yield self.callGet(('builds',), resultSpec=resultSpec)

        for build in builds:
            self.validateData(build)

        self.assertEqual(sorted([b['number'] for b in builds]), [3, 4])

    @defer.inlineCallbacks
    def test_get_worker(self):
        builds = yield self.callGet(('workers', 13, 'builds'))

        for build in builds:
            self.validateData(build)

        self.assertEqual(sorted([b['number'] for b in builds]), [3, 4])

    @defer.inlineCallbacks
    def test_get_complete(self):
        resultSpec = resultspec.OptimisedResultSpec(
            filters=[resultspec.Filter('complete', 'eq', [False])]
        )
        builds = yield self.callGet(('builds',), resultSpec=resultSpec)

        for build in builds:
            self.validateData(build)

        self.assertEqual(sorted([b['number'] for b in builds]), [3, 4])

    @defer.inlineCallbacks
    def test_get_complete_at(self):
        resultSpec = resultspec.OptimisedResultSpec(
            filters=[resultspec.Filter('complete_at', 'eq', [None])]
        )
        builds = yield self.callGet(('builds',), resultSpec=resultSpec)

        for build in builds:
            self.validateData(build)

        self.assertEqual(sorted([b['number'] for b in builds]), [3, 4])

    @defer.inlineCallbacks
    def test_properties_injection(self):
        resultSpec = resultspec.OptimisedResultSpec(
            properties=[resultspec.Property(b'property', 'eq', ['reason'])]
        )
        builds = yield self.callGet(('builds',), resultSpec=resultSpec)

        for build in builds:
            self.validateData(build)

        self.assertTrue(any(('reason' in b['properties']) for b in builds))

    @defer.inlineCallbacks
    def test_get_filter_eq(self):
        resultSpec = resultspec.OptimisedResultSpec(
            filters=[resultspec.Filter('builderid', 'eq', [78, 79])]
        )
        builds = yield self.callGet(('builds',), resultSpec=resultSpec)

        for b in builds:
            self.validateData(b)

        self.assertEqual(sorted([b['number'] for b in builds]), [5, 6])

    @defer.inlineCallbacks
    def test_get_filter_ne(self):
        resultSpec = resultspec.OptimisedResultSpec(
            filters=[resultspec.Filter('builderid', 'ne', [78, 79])]
        )
        builds = yield self.callGet(('builds',), resultSpec=resultSpec)

        for b in builds:
            self.validateData(b)

        self.assertEqual(sorted([b['number'] for b in builds]), [3, 4])


class Build(interfaces.InterfaceTests, TestReactorMixin, unittest.TestCase):
    new_build_event = {
        'builderid': 10,
        'buildid': 100,
        'buildrequestid': 13,
        'workerid': 20,
        'complete': False,
        'complete_at': None,
        "locks_duration_s": 0,
        'masterid': 824,
        'number': 43,
        'results': None,
        'started_at': epoch2datetime(1),
        'state_string': 'created',
        'properties': {},
    }

    @defer.inlineCallbacks
    def setUp(self):
        self.setup_test_reactor()
        self.master = yield fakemaster.make_master(self, wantMq=True, wantDb=True, wantData=True)
        self.rtype = builds.Build(self.master)

        yield self.master.db.insert_test_data([
            fakedb.Builder(id=10),
            fakedb.Master(id=824),
            fakedb.Worker(id=20, name='wrk'),
            fakedb.Buildset(id=999),
            fakedb.BuildRequest(id=499, buildsetid=999, builderid=10),
            fakedb.BuildRequest(id=13, buildsetid=999, builderid=10),
            fakedb.Build(
                id=99, builderid=10, masterid=824, workerid=20, buildrequestid=499, number=42
            ),
        ])

    @defer.inlineCallbacks
    def do_test_callthrough(
        self,
        dbMethodName,
        method,
        exp_retval=(1, 2),
        exp_args=None,
        exp_kwargs=None,
        *args,
        **kwargs,
    ):
        m = mock.Mock(return_value=defer.succeed(exp_retval))
        setattr(self.master.db.builds, dbMethodName, m)
        res = yield method(*args, **kwargs)
        self.assertIdentical(res, exp_retval)
        m.assert_called_with(*(exp_args or args), **(exp_kwargs or kwargs))

    @defer.inlineCallbacks
    def do_test_event(self, method, exp_events=None, *args, **kwargs):
        self.reactor.advance(1)
        if exp_events is None:
            exp_events = []
        yield method(*args, **kwargs)
        self.master.mq.assertProductions(exp_events)

    def test_signature_addBuild(self):
        @self.assertArgSpecMatches(
            self.master.data.updates.addBuild,  # fake
            self.rtype.addBuild,
        )  # real
        def addBuild(self, builderid, buildrequestid, workerid):
            pass

    def test_addBuild(self):
        return self.do_test_callthrough(
            'addBuild',
            self.rtype.addBuild,
            builderid=10,
            buildrequestid=13,
            workerid=20,
            exp_kwargs={
                "builderid": 10,
                "buildrequestid": 13,
                "workerid": 20,
                "masterid": self.master.masterid,
                "state_string": 'created',
            },
        )

    def test_addBuildEvent(self):
        @defer.inlineCallbacks
        def addBuild(*args, **kwargs):
            buildid, _ = yield self.rtype.addBuild(*args, **kwargs)
            yield self.rtype.generateNewBuildEvent(buildid)
            return None

        return self.do_test_event(
            addBuild,
            builderid=10,
            buildrequestid=13,
            workerid=20,
            exp_events=[
                (('builders', '10', 'builds', '43', 'new'), self.new_build_event),
                (('builds', '100', 'new'), self.new_build_event),
                (('workers', '20', 'builds', '100', 'new'), self.new_build_event),
            ],
        )

    def test_signature_setBuildStateString(self):
        @self.assertArgSpecMatches(
            self.master.data.updates.setBuildStateString,  # fake
            self.rtype.setBuildStateString,
        )  # real
        def setBuildStateString(self, buildid, state_string):
            pass

    def test_setBuildStateString(self):
        return self.do_test_callthrough(
            'setBuildStateString', self.rtype.setBuildStateString, buildid=10, state_string='a b'
        )

    def test_signature_add_build_locks_duration(self):
        @self.assertArgSpecMatches(
            self.master.data.updates.add_build_locks_duration, self.rtype.add_build_locks_duration
        )
        def add_build_locks_duration(self, buildid, duration_s):
            pass

    def test_add_build_locks_duration(self):
        return self.do_test_callthrough(
            "add_build_locks_duration",
            self.rtype.add_build_locks_duration,
            exp_retval=None,
            buildid=10,
            duration_s=5,
        )

    def test_signature_finishBuild(self):
        @self.assertArgSpecMatches(
            self.master.data.updates.finishBuild,  # fake
            self.rtype.finishBuild,
        )  # real
        def finishBuild(self, buildid, results):
            pass

    def test_finishBuild(self):
        return self.do_test_callthrough(
            'finishBuild', self.rtype.finishBuild, buildid=15, results=3
        )
