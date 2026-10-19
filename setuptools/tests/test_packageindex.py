import sys
import os
import io
import re
import distutils.errors
import platform
import urllib.parse
import urllib.request
import urllib.error
import http.client

import pytest

import setuptools.package_index
from .textwrap import DALS


class TestPackageIndex:
    def test_regex(self):
        hash_url = 'http://other_url?:action=show_md5&amp;'
        hash_url += 'digest=0123456789abcdef0123456789abcdef'
        doc = """
            <a href="http://some_url">Name</a>
            (<a title="MD5 hash"
            href="{hash_url}">md5</a>)
        """.lstrip().format(
            **locals()
        )
        assert setuptools.package_index.PYPI_MD5.match(doc)

    def test_bad_url_bad_port(self):
        index = setuptools.package_index.PackageIndex()
        url = 'http://127.0.0.1:0/nonesuch/test_package_index'
        try:
            v = index.open_url(url)
        except Exception as exc:
            assert url in str(exc)
        else:
            assert isinstance(v, urllib.error.HTTPError)

    def test_bad_url_typo(self):
        # issue 16
        # easy_install inquant.contentmirror.plone breaks because of a typo
        # in its home URL
        index = setuptools.package_index.PackageIndex(hosts=('www.example.com',))

        url = (
            'url:%20https://svn.plone.org/svn'
            '/collective/inquant.contentmirror.plone/trunk'
        )
        try:
            v = index.open_url(url)
        except Exception as exc:
            assert url in str(exc)
        else:
            assert isinstance(v, urllib.error.HTTPError)

    def test_bad_url_bad_status_line(self):
        index = setuptools.package_index.PackageIndex(hosts=('www.example.com',))

        def _urlopen(*args):
            raise http.client.BadStatusLine('line')

        index.opener = _urlopen
        url = 'http://example.com'
        try:
            index.open_url(url)
        except Exception as exc:
            assert 'line' in str(exc)
        else:
            raise AssertionError('Should have raise here!')

    def test_bad_url_double_scheme(self):
        """
        A bad URL with a double scheme should raise a DistutilsError.
        """
        index = setuptools.package_index.PackageIndex(hosts=('www.example.com',))

        # issue 20
        url = 'http://http://svn.pythonpaste.org/Paste/wphp/trunk'
        try:
            index.open_url(url)
        except distutils.errors.DistutilsError as error:
            msg = str(error)
            assert (
                'nonnumeric port' in msg
                or 'getaddrinfo failed' in msg
                or 'Name or service not known' in msg
            )
            return
        raise RuntimeError("Did not raise")

    def test_bad_url_screwy_href(self):
        index = setuptools.package_index.PackageIndex(hosts=('www.example.com',))

        # issue #160
        if sys.version_info[0] == 2 and sys.version_info[1] == 7:
            # this should not fail
            url = 'http://example.com'
            page = '<a href="http://www.famfamfam.com](' 'http://www.famfamfam.com/">'
            index.process_index(url, page)

    def test_url_ok(self):
        index = setuptools.package_index.PackageIndex(hosts=('www.example.com',))
        url = 'file:///tmp/test_package_index'
        assert index.url_ok(url, True)

    def test_parse_bdist_wininst(self):
        parse = setuptools.package_index.parse_bdist_wininst

        actual = parse('reportlab-2.5.win32-py2.4.exe')
        expected = 'reportlab-2.5', '2.4', 'win32'
        assert actual == expected

        actual = parse('reportlab-2.5.win32.exe')
        expected = 'reportlab-2.5', None, 'win32'
        assert actual == expected

        actual = parse('reportlab-2.5.win-amd64-py2.7.exe')
        expected = 'reportlab-2.5', '2.7', 'win-amd64'
        assert actual == expected

        actual = parse('reportlab-2.5.win-amd64.exe')
        expected = 'reportlab-2.5', None, 'win-amd64'
        assert actual == expected

    def test__vcs_split_rev_from_url(self):
        """
        Test the basic usage of _vcs_split_rev_from_url
        """
        vsrfu = setuptools.package_index.PackageIndex._vcs_split_rev_from_url
        url, rev = vsrfu('https://example.com/bar@2995')
        assert url == 'https://example.com/bar'
        assert rev == '2995'

    def test_local_index(self, tmpdir):
        """
        local_open should be able to read an index from the file system.
        """
        index_file = tmpdir / 'index.html'
        with index_file.open('w') as f:
            f.write('<div>content</div>')
        url = 'file:' + urllib.request.pathname2url(str(tmpdir)) + '/'
        res = setuptools.package_index.local_open(url)
        assert 'content' in res.read()

    def test_egg_fragment(self):
        """
        EGG fragments must comply to PEP 440
        """
        epoch = [
            '',
            '1!',
        ]
        releases = [
            '0',
            '0.0',
            '0.0.0',
        ]
        pre = [
            'a0',
            'b0',
            'rc0',
        ]
        post = ['.post0']
        dev = [
            '.dev0',
        ]
        local = [
            ('', ''),
            ('+ubuntu.0', '+ubuntu.0'),
            ('+ubuntu-0', '+ubuntu.0'),
            ('+ubuntu_0', '+ubuntu.0'),
        ]
        versions = [
            [''.join([e, r, p, loc]) for loc in locs]
            for e in epoch
            for r in releases
            for p in sum([pre, post, dev], [''])
            for locs in local
        ]
        for v, vc in versions:
            dists = list(
                setuptools.package_index.distros_for_url(
                    'http://example.com/example-foo.zip#egg=example-foo-' + v
                )
            )
            assert dists[0].version == ''
            assert dists[1].version == vc

    def test_download_git_with_rev(self, tmp_path, fake_process):
        url = 'git+https://github.example/group/project@master#egg=foo'
        index = setuptools.package_index.PackageIndex()

        expected_dir = tmp_path / 'project@master'
        fake_process.register_subprocess([
            'git',
            'clone',
            '--quiet',
            'https://github.example/group/project',
            str(expected_dir),
        ])
        fake_process.register_subprocess([
            'git',
            '-C',
            str(expected_dir),
            'checkout',
            '--quiet',
            'master'
        ])

        result = index.download(url, tmp_path)

        assert result == str(expected_dir)
        assert len(fake_process.calls) == 2

    def test_download_git_no_rev(self, tmp_path, fake_process):
        url = 'git+https://github.example/group/project#egg=foo'
        index = setuptools.package_index.PackageIndex()

        expected_dir = tmp_path / 'project'
        fake_process.register_subprocess([
            'git',
            'clone',
            '--quiet',
            'https://github.example/group/project',
            str(expected_dir),
        ])
        index.download(url, tmp_path)

    def test_download_svn(self, tmpdir):
        url = 'svn+https://svn.example/project#egg=foo'
        index = setuptools.package_index.PackageIndex()

        msg = r".*SVN download is not supported.*"
        with pytest.raises(distutils.errors.DistutilsError, match=msg):
            index.download(url, str(tmpdir))

    @pytest.mark.parametrize(
        'url, dest_name, expected_commands',
        [
            pytest.param(
                'git+https://github.example/group/project;touch${IFS}pwned#egg=foo',
                'project;touch${IFS}pwned',
                [
                    [
                        'git',
                        'clone',
                        '--quiet',
                        'https://github.example/group/project;touch${IFS}pwned',
                        '<dest>',
                    ],
                ],
                id='git-clone-url',
            ),
            pytest.param(
                'git://github.example/project`touch${IFS}pwned`#egg=foo',
                'project`touch${IFS}pwned`',
                [
                    [
                        'git',
                        'clone',
                        '--quiet',
                        'git://github.example/project`touch${IFS}pwned`',
                        '<dest>',
                    ],
                ],
                id='git-protocol-url',
            ),
            pytest.param(
                'git+https://github.example/group/project@master;touch${IFS}pwned'
                '#egg=foo',
                'project@master;touch${IFS}pwned',
                [
                    [
                        'git',
                        'clone',
                        '--quiet',
                        'https://github.example/group/project',
                        '<dest>',
                    ],
                    [
                        'git',
                        '-C',
                        '<dest>',
                        'checkout',
                        '--quiet',
                        'master;touch${IFS}pwned',
                    ],
                ],
                id='git-checkout-rev',
            ),
            pytest.param(
                'git+https://github.example/group/project%3Btouch%20pwned#egg=foo',
                'project;touch pwned',
                [
                    [
                        'git',
                        'clone',
                        '--quiet',
                        'https://github.example/group/project%3Btouch%20pwned',
                        '<dest>',
                    ],
                ],
                id='git-clone-destination',
            ),
            pytest.param(
                'hg+https://hg.example/project$(touch${IFS}pwned)#egg=foo',
                'project$(touch${IFS}pwned)',
                [
                    [
                        'hg',
                        'clone',
                        '--quiet',
                        'https://hg.example/project$(touch${IFS}pwned)',
                        '<dest>',
                    ],
                ],
                id='hg-clone-url',
            ),
            pytest.param(
                'hg+https://hg.example/project@tip;touch${IFS}pwned#egg=foo',
                'project@tip;touch${IFS}pwned',
                [
                    ['hg', 'clone', '--quiet', 'https://hg.example/project', '<dest>'],
                    [
                        'hg',
                        '--cwd',
                        '<dest>',
                        'up',
                        '-C',
                        '-r',
                        'tip;touch${IFS}pwned',
                        '-q',
                    ],
                ],
                id='hg-update-rev',
            ),
        ],
    )
    def test_download_vcs_no_shell_injection(
        self, tmp_path, fake_process, monkeypatch, url, dest_name, expected_commands
    ):
        """
        VCS downloads must never hand the URL, revision or destination
        to a shell (CVE-2024-6345); each one is passed as a single
        argument to the VCS command.
        """
        shell_commands = []
        monkeypatch.setattr(os, 'system', lambda cmd: shell_commands.append(cmd) or 0)

        dest = str(tmp_path / dest_name)
        commands = [
            [dest if arg == '<dest>' else arg for arg in command]
            for command in expected_commands
        ]
        for command in commands:
            fake_process.register_subprocess(command)

        index = setuptools.package_index.PackageIndex()
        result = index.download(url, tmp_path)

        assert shell_commands == []
        for command in commands:
            assert fake_process.call_count(command) == 1
        assert len(fake_process.calls) == len(commands)
        assert result == dest

    @pytest.mark.parametrize(
        'name, expected',
        [
            ('/home/user/.ssh/authorized_keys', '_home_user_.ssh_authorized_keys'),
            ('../../../etc/passwd', '______etc_passwd'),
            ('..', '_'),
            ('..\\..\\evil.txt', '____evil.txt'),
            ('C:\\Windows\\evil.txt', 'C__Windows_evil.txt'),
            ('D:evil.txt', 'D_evil.txt'),
            ('D:../foo', 'D___foo'),
            ('foo..bar-1.0.tar.gz', 'foo..bar-1.0.tar.gz'),
            ('setuptools-68.2.2.tar.gz', 'setuptools-68.2.2.tar.gz'),
        ],
    )
    def test_sanitize(self, name, expected):
        assert setuptools.package_index.PackageIndex._sanitize(name) == expected

    @pytest.mark.parametrize(
        'url, expected_name',
        [
            pytest.param(
                'https://files.example/packages/setuptools-68.2.2.tar.gz',
                'setuptools-68.2.2.tar.gz',
                id='plain',
            ),
            pytest.param(
                'https://anyhost/%2fhome%2fuser%2f.ssh%2fauthorized_keys',
                '_home_user_.ssh_authorized_keys',
                id='encoded-absolute-path',
            ),
            pytest.param(
                'https://anyhost/..%2f..%2f..%2fetc%2fpasswd',
                '______etc_passwd',
                id='encoded-parent-dirs',
            ),
            pytest.param(
                'https://anyhost/%2e%2e',
                '_',
                id='encoded-parent-dir-only',
            ),
            pytest.param(
                'https://anyhost/..%5c..%5cevil.txt',
                '____evil.txt',
                id='encoded-backslash-parent-dirs',
            ),
            pytest.param(
                'https://anyhost/C%3a%5cWindows%5cevil.txt',
                'C__Windows_evil.txt',
                id='encoded-drive-absolute-path',
            ),
            pytest.param(
                'https://anyhost/D%3aevil.txt',
                'D_evil.txt',
                id='encoded-drive-relative-path',
            ),
            pytest.param(
                'https://anyhost/foo..bar-1.0.tar.gz',
                'foo..bar-1.0.tar.gz',
                id='embedded-dots-preserved',
            ),
            pytest.param(
                'https://anyhost/foo-1.0-py3.8.egg.zip',
                'foo-1.0-py3.8.egg',
                id='egg-zip',
            ),
            pytest.param(
                'https://anyhost/',
                '__downloaded__',
                id='empty-path',
            ),
        ],
    )
    def test_resolve_download_filename(self, tmp_path, url, expected_name):
        """
        The download target derived from the URL always lands directly
        inside tmpdir (CVE-2025-47273).
        """
        resolve = setuptools.package_index.PackageIndex._resolve_download_filename
        filename = resolve(url, tmp_path)
        assert os.path.dirname(filename) == str(tmp_path)
        assert os.path.basename(filename) == expected_name

    def test_resolve_download_filename_outside_tmpdir(self, tmp_path, monkeypatch):
        """
        Should a name ever get past sanitization, a target that does not
        resolve within tmpdir is still rejected.
        """
        PackageIndex = setuptools.package_index.PackageIndex
        monkeypatch.setattr(PackageIndex, '_sanitize', staticmethod(lambda name: name))
        tmpdir = tmp_path / 'dl'
        victim = tmp_path / 'victim' / 'keys'
        url = 'https://attacker.example/' + urllib.parse.quote(str(victim), safe='')

        with pytest.raises(ValueError, match='Invalid filename'):
            PackageIndex._resolve_download_filename(url, str(tmpdir))

    def test_download_path_traversal(self, tmp_path, monkeypatch):
        """
        A URL whose last path segment decodes to an absolute path must
        not write the download outside tmpdir (CVE-2025-47273).
        """

        class FakeResponse(io.BytesIO):
            def info(self):
                return http.client.HTTPMessage()

        payload = b'ssh-rsa attacker-key\n'
        monkeypatch.setattr(
            setuptools.package_index.PackageIndex,
            'open_url',
            lambda self, url, warning=None: FakeResponse(payload),
        )

        tmpdir = tmp_path / 'dl'
        tmpdir.mkdir()
        victim_dir = tmp_path / 'victim'
        victim_dir.mkdir()
        victim = victim_dir / 'keys'
        url = 'https://attacker.example/' + urllib.parse.quote(str(victim), safe='')

        index = setuptools.package_index.PackageIndex()
        result = index.download(url, str(tmpdir))

        assert not victim.exists()
        assert os.listdir(str(victim_dir)) == []
        assert os.path.dirname(result) == str(tmpdir)
        with open(result, 'rb') as downloaded:
            assert downloaded.read() == payload

    def test_download_vcs_path_traversal(self, tmp_path, fake_process):
        """
        A VCS URL whose last path segment decodes to an absolute path must
        not clone outside tmpdir (CVE-2025-47273).
        """
        tmpdir = tmp_path / 'dl'
        victim = tmp_path / 'victim'
        clone_url = 'https://github.example/' + urllib.parse.quote(str(victim), safe='')
        url = 'git+' + clone_url + '#egg=foo'

        sanitized = re.sub(r'[:/\\]', '_', str(victim))
        expected_dest = os.path.join(str(tmpdir), sanitized)
        fake_process.register_subprocess([
            'git',
            'clone',
            '--quiet',
            clone_url,
            expected_dest,
        ])

        index = setuptools.package_index.PackageIndex()
        result = index.download(url, str(tmpdir))

        assert result == expected_dest
        assert os.path.dirname(result) == str(tmpdir)
        assert len(fake_process.calls) == 1


class TestContentCheckers:
    def test_md5(self):
        checker = setuptools.package_index.HashChecker.from_url(
            'http://foo/bar#md5=f12895fdffbd45007040d2e44df98478'
        )
        checker.feed('You should probably not be using MD5'.encode('ascii'))
        assert checker.hash.hexdigest() == 'f12895fdffbd45007040d2e44df98478'
        assert checker.is_valid()

    def test_other_fragment(self):
        "Content checks should succeed silently if no hash is present"
        checker = setuptools.package_index.HashChecker.from_url(
            'http://foo/bar#something%20completely%20different'
        )
        checker.feed('anything'.encode('ascii'))
        assert checker.is_valid()

    def test_blank_md5(self):
        "Content checks should succeed if a hash is empty"
        checker = setuptools.package_index.HashChecker.from_url('http://foo/bar#md5=')
        checker.feed('anything'.encode('ascii'))
        assert checker.is_valid()

    def test_get_hash_name_md5(self):
        checker = setuptools.package_index.HashChecker.from_url(
            'http://foo/bar#md5=f12895fdffbd45007040d2e44df98478'
        )
        assert checker.hash_name == 'md5'

    def test_report(self):
        checker = setuptools.package_index.HashChecker.from_url(
            'http://foo/bar#md5=f12895fdffbd45007040d2e44df98478'
        )
        rep = checker.report(lambda x: x, 'My message about %s')
        assert rep == 'My message about md5'


@pytest.fixture
def temp_home(tmpdir, monkeypatch):
    key = (
        'USERPROFILE'
        if platform.system() == 'Windows' and sys.version_info > (3, 8)
        else 'HOME'
    )

    monkeypatch.setitem(os.environ, key, str(tmpdir))
    return tmpdir


class TestPyPIConfig:
    def test_percent_in_password(self, temp_home):
        pypirc = temp_home / '.pypirc'
        pypirc.write(
            DALS(
                """
            [pypi]
            repository=https://pypi.org
            username=jaraco
            password=pity%
        """
            )
        )
        cfg = setuptools.package_index.PyPIConfig()
        cred = cfg.creds_by_repository['https://pypi.org']
        assert cred.username == 'jaraco'
        assert cred.password == 'pity%'


@pytest.mark.timeout(1)
def test_REL_DoS():
    """
    REL should not hang on a contrived attack string.
    """
    setuptools.package_index.REL.search('< rel=' + ' ' * 2**12)
