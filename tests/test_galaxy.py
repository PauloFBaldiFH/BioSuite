from dataclasses import replace
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from biosuite.galaxy import GalaxyClient, GalaxyError, NoRedirect, Repository, ToolShedClient, ToolSpec, validate_url

REPO = Repository('abc123', 'iqtree', 'iuc', '123456abcdef', 'toolshed.g2.bx.psu.edu', 'Installed', False, False)


class Opener:
    def __init__(self, *results):
        self.results = list(results)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return io.BytesIO(json.dumps(result).encode())


def api_repo(status='Installed'):
    return {'id': REPO.id, 'name': REPO.name, 'owner': REPO.owner,
            'changeset_revision': REPO.revision, 'tool_shed': REPO.shed,
            'status': status, 'deleted': False, 'uninstalled': False}


class GalaxyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.env = patch.dict(os.environ, {'XDG_STATE_HOME': self.folder.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = GalaxyClient('http://localhost:8080/galaxy', 'test-secret')

    def test_connect_authenticated_user_and_list(self):
        self.client._opener = Opener({'id': 'user123'}, [api_repo()])
        self.assertEqual(self.client.connect(), [REPO])
        self.assertEqual(self.client._opener.requests[0].full_url,
                         'http://localhost:8080/galaxy/api/users/current')
        self.assertEqual(self.client._opener.requests[0].get_header('X-api-key'), 'test-secret')

    def test_install_payload_and_pending_state_are_preserved(self):
        opener = Opener([], [api_repo('Installing tool dependencies')], [api_repo('Installing tool dependencies')])
        self.client._opener = opener
        result = self.client.install(ToolSpec(REPO.name, REPO.owner, REPO.revision))
        request = opener.requests[1]
        self.assertEqual(request.method, 'POST')
        self.assertTrue(request.full_url.endswith('/install_repository_revision'))
        payload = json.loads(request.data)
        self.assertTrue(payload['install_resolver_dependencies'])
        self.assertTrue(payload['install_repository_dependencies'])
        self.assertEqual(payload['changeset_revision'], REPO.revision)
        self.assertEqual(result[0].display_status, 'Installing tool dependencies')

    def test_existing_revision_is_not_installed_twice(self):
        opener = Opener([api_repo()])
        self.client._opener = opener
        with self.assertRaisesRegex(GalaxyError, 'já está registrada'):
            self.client.install(ToolSpec(REPO.name, REPO.owner, REPO.revision))
        self.assertEqual(len(opener.requests), 1)

    def test_uninstall_targets_exact_id_and_preserves_returned_state(self):
        removed = {**api_repo(), 'uninstalled': True, 'status': 'Uninstalled'}
        opener = Opener([api_repo()], {'message': 'removed'}, [removed])
        self.client._opener = opener
        result = self.client.uninstall(REPO)
        self.assertEqual(opener.requests[1].method, 'DELETE')
        self.assertTrue(opener.requests[1].full_url.endswith('/abc123?remove_from_disk=true'))
        self.assertEqual(result[0].display_status, 'Desinstalado')

    def test_changed_repository_is_not_removed(self):
        opener = Opener([api_repo('Installing')])
        self.client._opener = opener
        with self.assertRaisesRegex(GalaxyError, 'mudou'):
            self.client.uninstall(REPO)
        self.assertEqual(len(opener.requests), 1)

    def test_an_installing_repository_is_not_removed(self):
        self.client._opener = Opener([api_repo('Installing')])
        with self.assertRaisesRegex(GalaxyError, 'Estado incompatível'):
            self.client.uninstall(replace(REPO, status='Installing'))

    def test_timeout_does_not_retry_mutation(self):
        opener = Opener([], URLError('test-secret'))
        self.client._opener = opener
        with self.assertRaisesRegex(GalaxyError, 'pode continuar') as caught:
            self.client.install(ToolSpec(REPO.name, REPO.owner, REPO.revision))
        self.assertNotIn('test-secret', str(caught.exception))
        self.assertEqual(len(opener.requests), 2)

    def test_permission_error_does_not_expose_response(self):
        self.client._opener = Opener(HTTPError('url', 403, 'test-secret', {}, io.BytesIO(b'test-secret')))
        with self.assertRaisesRegex(GalaxyError, 'Acesso negado') as caught:
            self.client.repositories()
        self.assertNotIn('test-secret', str(caught.exception))

    def test_public_revisions_never_receive_galaxy_api_key(self):
        opener = Opener([REPO.revision])
        self.client._opener = opener
        self.assertEqual(self.client.revisions('iqtree', 'iuc'), [REPO.revision])
        self.assertIsNone(opener.requests[0].get_header('X-api-key'))
        self.assertTrue(opener.requests[0].full_url.startswith('https://toolshed.g2.bx.psu.edu/api/repositories/'))

    def test_local_mutation_lock_blocks_second_client(self):
        other = GalaxyClient(self.client.url, 'another-key')
        with self.client._mutation_lock():
            with self.assertRaisesRegex(GalaxyError, 'Outra operação'):
                with other._mutation_lock():
                    self.fail('Lock deveria impedir concorrência')

    def test_url_validation_and_redirect_guard(self):
        for url in ('http://remote.example', 'https://user:pass@example.org',
                    'https://example.org/?key=secret', 'https://example.org/#fragment', 'file:///tmp/a'):
            with self.subTest(url=url), self.assertRaises(GalaxyError):
                validate_url(url)
        self.assertEqual(validate_url('https://example.org/galaxy/'), 'https://example.org/galaxy')
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.org'))

    def test_invalid_revision_and_json_error_fail(self):
        with self.assertRaises(GalaxyError):
            self.client.install(ToolSpec('iqtree', 'iuc', 'latest'))
        self.client._opener = Opener({'status': 'error', 'error': 'test-secret'})
        with self.assertRaises(GalaxyError) as caught:
            self.client.repositories()
        self.assertNotIn('test-secret', str(caught.exception))

    def test_public_search_normalizes_results_and_paginates(self):
        shed = ToolShedClient()
        opener = Opener({'hits': [{'repository': {'name': 'fastqc', 'repo_owner_username': 'devteam',
                                                  'description': 'Quality report'}}], 'total_results': '21'})
        shed._opener = opener
        page = shed.search('fast qc', page=2)
        self.assertEqual(page.hits[0].owner, 'devteam')
        self.assertEqual(page.total, 21)
        self.assertTrue(page.has_next)
        request = opener.requests[0]
        self.assertEqual(request.method, 'GET')
        self.assertIn('q=fast+qc&page=2&page_size=10', request.full_url)
        self.assertIsNone(request.get_header('X-api-key'))

    def test_empty_search_page_and_invalid_payload(self):
        shed = ToolShedClient()
        shed._opener = Opener({'hits': [], 'total_results': 0})
        page = shed.search('not-found')
        self.assertFalse(page.has_next)
        self.assertEqual(page.hits, ())
        for result in ([], {'hits': {}, 'total_results': 0}, {'hits': [], 'total_results': -1},
                       {'hits': [{'repository': {'name': 'unknown'}}], 'total_results': 1}):
            with self.subTest(result=result), self.assertRaises(GalaxyError):
                shed._opener = Opener(result)
                shed.search('test')

    def test_search_rejects_invalid_input_before_network(self):
        shed = ToolShedClient()
        shed._opener = Opener()
        for query, page in [('', 1), ('x' * 201, 1), ('line\nbreak', 1), ('name', 0)]:
            with self.subTest(query=query, page=page), self.assertRaises(GalaxyError):
                shed.search(query, page)
        self.assertEqual(shed._opener.requests, [])
