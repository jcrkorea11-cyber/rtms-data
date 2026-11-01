import io
import json
import ssl
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import collect
import resilient_http as http


class RecoveryTests(unittest.TestCase):
    def test_handshake_timeout_recovers(self):
        with patch.object(http.urllib.request, 'urlopen', side_effect=[urllib.error.URLError(TimeoutError('handshake')), io.BytesIO(b'ok')]) as req, patch.object(http.time, 'sleep') as sleep:
            self.assertEqual(http.get_text('https://example.invalid/?secret=hidden'), 'ok')
            self.assertEqual(req.call_args_list[0].kwargs['timeout'], 90)
            self.assertEqual(req.call_args_list[1].kwargs['timeout'], 120)
            sleep.assert_called_once()

    def test_retry_exhaustion_is_bounded_and_redacted(self):
        with patch.object(http.urllib.request, 'urlopen', side_effect=urllib.error.URLError(TimeoutError('secret'))) as req, patch.object(http.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'exhausted') as error:
                http.get_text('https://example.invalid/?secret=hidden')
            self.assertNotIn('secret', str(error.exception))
            self.assertEqual(req.call_count, 4)

    def test_certificate_and_auth_errors_are_not_retried(self):
        for error in [urllib.error.URLError(ssl.SSLCertVerificationError('invalid')), urllib.error.HTTPError('secret', 403, 'denied', {}, None)]:
            with patch.object(http.urllib.request, 'urlopen', side_effect=error) as req:
                with self.assertRaises(RuntimeError): http.get_text('secret')
                self.assertEqual(req.call_count, 1)

    def test_retry_after(self):
        err = urllib.error.HTTPError('secret', 429, 'rate limit', {'Retry-After': '17'}, None)
        with patch.object(http.urllib.request, 'urlopen', side_effect=[err, io.BytesIO(b'ok')]), patch.object(http.time, 'sleep') as sleep:
            self.assertEqual(http.get_text('secret'), 'ok')
            sleep.assert_called_once_with(17)

    def test_long_retry_after_aborts(self):
        err = urllib.error.HTTPError('secret', 503, 'busy', {'Retry-After': '600'}, None)
        with patch.object(http.urllib.request, 'urlopen', side_effect=err) as req:
            with self.assertRaises(RuntimeError): http.get_text('secret')
            self.assertEqual(req.call_count, 1)

    def test_pagination(self):
        xml = '<response><header><resultCode>000</resultCode></header><body><totalCount>2</totalCount><items><item><dealYear>2025</dealYear></item></items></body></response>'
        with patch.object(collect, 'BATCH', 1), patch.object(collect, 'http', return_value=xml) as req:
            self.assertEqual(len(collect.molit_items('11320', '202508')), 2)
            self.assertIn('pageNo=2', req.call_args.args[0])

    def test_incomplete_and_error_xml_rejected(self):
        for xml in ['<response/>', '<response><resultCode>000</resultCode><totalCount>1</totalCount></response>', '<response><resultCode>30</resultCode></response>']:
            with patch.object(collect, 'http', return_value=xml):
                self.assertIsNone(collect.molit_items('11560', '202511'))

    def test_failed_month_preserves_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'nrg_11320_도봉구.csv'
            path.write_text('original')
            with patch.object(collect, 'OUT', Path(tmp)), patch.object(collect, 'MOLIT_KEY', 'test'), patch.object(collect, 'GUS', {'11320':'도봉구'}), patch.object(collect, 'months', return_value=['202508']), patch.object(collect, 'molit_items', return_value=None):
                with self.assertRaises(RuntimeError): collect.run_commercial()
            self.assertEqual(path.read_text(), 'original')

    def test_full_run_failure_keeps_all_published_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'summary.json'
            target.write_text('original')
            with patch.object(collect, 'OUT', Path(tmp)), patch.object(collect, 'run_housing', return_value={}), patch.object(collect, 'run_commercial', side_effect=RuntimeError('failed')):
                with self.assertRaises(RuntimeError): collect.main()
                self.assertEqual(collect.OUT, Path(tmp))
            self.assertEqual(target.read_text(), 'original')

    def test_comparison_counts_duplicate_rows_and_changes(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            (Path(a)/'x.csv').write_text('a,b\n1,2\n1,2\n')
            (Path(b)/'x.csv').write_text('b,a\n2,1\n3,2\n')
            self.assertEqual(collect.compare_snapshots(Path(a), Path(b))['x.csv'], {'before':2,'after':2,'added':1,'removed':1})


if __name__ == '__main__':
    unittest.main()
