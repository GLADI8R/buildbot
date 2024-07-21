# This file is part of Buildbot. Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members


import json as jsonmodule

from twisted.internet import defer
from twisted.logger import Logger
from zope.interface import implementer

from buildbot import util
from buildbot.interfaces import IHttpResponse
from buildbot.util import httpclientservice
from buildbot.util import service
from buildbot.util import toJson
from buildbot.util import unicode2bytes

log = Logger()


@implementer(IHttpResponse)
class ResponseWrapper:
    def __init__(self, code, content, url=None):
        self._content = content
        self._code = code
        self._url = url

    def content(self):
        content = unicode2bytes(self._content)
        return defer.succeed(content)

    def json(self):
        return defer.succeed(jsonmodule.loads(self._content))

    @property
    def code(self):
        return self._code

    @property
    def url(self):
        return self._url


class HTTPClientService(service.SharedService):
    """HTTPClientService is a SharedService class that fakes http requests for buildbot http
    service testing.

    This class is named the same as the real HTTPClientService so that it could replace the real
    class in tests. If a test creates this class earlier than the real one, fake is going to be
    used until the master is destroyed. Whenever a master wants to create real
    HTTPClientService, it will find an existing fake service with the same name and use it
    instead.
    """

    quiet = False

    def __init__(
        self, base_url, auth=None, headers=None, debug=None, verify=None, skipEncoding=None
    ):
        assert not base_url.endswith("/"), "baseurl should not end with /"
        super().__init__()
        self._base_url = base_url
        self._auth = auth

        self._headers = headers
        self._session = None
        self._expected = []

    def updateHeaders(self, headers):
        if self._headers is None:
            self._headers = {}
        self._headers.update(headers)

    @classmethod
    @defer.inlineCallbacks
    def getService(cls, master, case, *args, **kwargs):
        def assertNotCalled(self, *_args, **_kwargs):
            case.fail(
                f"HTTPClientService called with *{_args!r}, **{_kwargs!r} "
                f"while should be called *{args!r} **{kwargs!r}"
            )

        case.patch(httpclientservice.HTTPClientService, "__init__", assertNotCalled)

        service = yield super().getService(master, *args, **kwargs)
        service.case = case
        case.addCleanup(service.assertNoOutstanding)
        return service

    def expect(
        self,
        method,
        ep,
        params=None,
        headers=None,
        data=None,
        json=None,
        code=200,
        content=None,
        content_json=None,
        files=None,
        verify=None,
        cert=None,
        processing_delay_s=None,
    ):
        if content is not None and content_json is not None:
            return ValueError("content and content_json cannot be both specified")

        if content_json is not None:
            content = jsonmodule.dumps(content_json, default=toJson)

        self._expected.append({
            "method": method,
            "ep": ep,
            "params": params,
            "headers": headers,
            "data": data,
            "json": json,
            "code": code,
            "content": content,
            "files": files,
            "verify": verify,
            "cert": cert,
            "processing_delay_s": processing_delay_s,
        })
        return None

    def assertNoOutstanding(self):
        self.case.assertEqual(
            0, len(self._expected), f"expected more http requests:\n {self._expected!r}"
        )

    @defer.inlineCallbacks
    def _doRequest(
        self,
        method,
        ep,
        params=None,
        headers=None,
        data=None,
        json=None,
        files=None,
        timeout=None,
        verify=None,
        cert=None,
    ):
        if ep.startswith('http://') or ep.startswith('https://'):
            pass
        else:
            assert ep == "" or ep.startswith("/"), "ep should start with /: " + ep

        if not self.quiet:
            log.debug(
                "{method} {ep} {params!r} <- {data!r}",
                method=method,
                ep=ep,
                params=params,
                data=data or json,
            )
        if json is not None:
            # ensure that the json is really jsonable
            jsonmodule.dumps(json, default=toJson)
        if files is not None:
            files = dict((k, v.read()) for (k, v) in files.items())
        if not self._expected:
            raise AssertionError(
                f"Not expecting a request, while we got: method={method!r}, ep={ep!r}, "
                f"params={params!r}, headers={headers!r}, data={data!r}, json={json!r}, "
                f"files={files!r}"
            )
        expect = self._expected.pop(0)
        processing_delay_s = expect.pop("processing_delay_s")

        # pylint: disable=too-many-boolean-expressions
        if (
            expect["method"] != method
            or expect["ep"] != ep
            or expect["params"] != params
            or expect["headers"] != headers
            or expect["data"] != data
            or expect["json"] != json
            or expect["files"] != files
            or expect["verify"] != verify
            or expect["cert"] != cert
        ):
            raise AssertionError(
                "expecting:\n"
                f"method={expect['method']!r}, "
                f"ep={expect['ep']!r}, "
                f"params={expect['params']!r}, "
                f"headers={expect['headers']!r}, "
                f"data={expect['data']!r}, "
                f"json={expect['json']!r}, "
                f"files={expect['files']!r}, "
                f"verify={expect['verify']!r}, "
                f"cert={expect['cert']!r}"
                "\ngot      :\n"
                f"method={method!r}, "
                f"ep={ep!r}, "
                f"params={params!r}, "
                f"headers={headers!r}, "
                f"data={data!r}, "
                f"json={json!r}, "
                f"files={files!r}, "
                f"verify={verify!r}, "
                f"cert={cert!r}"
            )
        if not self.quiet:
            log.debug(
                "{method} {ep} -> {code} {content!r}",
                method=method,
                ep=ep,
                code=expect['code'],
                content=expect['content'],
            )

        if processing_delay_s is not None:
            yield util.asyncSleep(1, reactor=self.master.reactor)

        return ResponseWrapper(expect['code'], expect['content'])

    # lets be nice to the auto completers, and don't generate that code
    def get(self, ep, **kwargs):
        return self._doRequest('get', ep, **kwargs)

    def put(self, ep, **kwargs):
        return self._doRequest('put', ep, **kwargs)

    def delete(self, ep, **kwargs):
        return self._doRequest('delete', ep, **kwargs)

    def post(self, ep, **kwargs):
        return self._doRequest('post', ep, **kwargs)
