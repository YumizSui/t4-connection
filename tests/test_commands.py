import os
from pathlib import Path
import signal
import socket
import sys
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Commands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), T4_CONFIG=str(self.home/'absent'),
                        PATH=f'{self.bin}:/usr/bin:/bin', LOG=str(self.home/'ssh.log'))
        self.mock('ssh', '''if [[ $* == *'cat .local/state'* ]]; then
printf '%s\\n' "${TEST_STATE:-r3n11 12345 testuser}"
else
printf '%s\\n' "$@" > "$LOG"
exit "${TEST_SSH_EXIT:-0}"
fi''')

    def mock(self, name, text):
        path = self.bin/name
        path.write_text('#!/bin/bash\n'+text+'\n')
        path.chmod(0o755)

    def run_cmd(self, name, *args):
        return subprocess.run([str(ROOT/name), *args], env=self.env, text=True, capture_output=True)

    def test_forward_isolated_and_loopback(self):
        self.assertEqual(self.run_cmd('local/t4-forward', '9000').returncode, 0)
        args = (self.home/'ssh.log').read_text().splitlines()
        for value in ['none', 'ControlMaster=no', 'ControlPersist=no', 'ExitOnForwardFailure=yes',
                      '127.0.0.1:9000:r3n11:12345', '-N', '-T']:
            self.assertIn(value, args)

    def test_forward_propagates_failure(self):
        self.env['TEST_SSH_EXIT'] = '255'
        self.assertEqual(self.run_cmd('local/t4-forward').returncode, 255)

    def test_state_is_never_executed(self):
        for state in ['r3n11 12345 testuser extra', 'r3n11 12345 testuser\necho bad',
                      '$(touch /tmp/t4-unsafe) 12345 user', 'r3n11 99999 testuser']:
            self.env['TEST_STATE'] = state
            self.assertNotEqual(self.run_cmd('local/t4-shell').returncode, 0)
        self.assertFalse((self.home/'ssh.log').exists())

    def test_shell_uses_state_user_and_port(self):
        self.assertEqual(self.run_cmd('local/t4-shell').returncode, 0)
        self.assertIn('testuser@r3n11', (self.home/'ssh.log').read_text())

    def test_bad_hours_and_dry_run(self):
        for hours in ['0', '25', '999', '1;echo bad']:
            self.assertNotEqual(self.run_cmd('local/t4-start', '--dry-run', hours).returncode, 0)
        self.assertEqual(self.run_cmd('local/t4-start', '--dry-run', '1', 'both').returncode, 0)
        self.assertFalse((self.home/'ssh.log').exists())

    def test_login_node_rejected(self):
        self.mock('hostname', 'echo login1')
        self.assertNotEqual(self.run_cmd('remote/start-code-server').returncode, 0)

    def test_service_cleanup_and_lock(self):
        self.mock('hostname', 'echo r3n11')
        self.mock('code-server', 'echo "HTTP server listening on http://0.0.0.0:8890/"; exec sleep 30')
        self.env['JOB_ID'] = '123'
        state = self.home/'.local/state/t4-connection/code-server'
        proc = subprocess.Popen([str(ROOT/'remote/start-code-server')], env=self.env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(40):
                if state.exists():
                    break
                time.sleep(.1)
            self.assertTrue(state.exists())
            self.assertNotEqual(self.run_cmd('remote/start-code-server').returncode, 0)
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
            self.assertFalse(state.exists())
            self.assertFalse(Path(str(state)+'.lock').exists())
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def wait_state(self, proc, service):
        state = self.home/'.local/state/t4-connection'/service
        for _ in range(100):
            if state.exists():
                return state.read_text().split()
            if proc.poll() is not None:
                self.fail('Service exited before publishing its endpoint')
            time.sleep(.05)
        self.fail('Service did not publish its endpoint')

    def stop_process(self, proc):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def test_remote_collision_changes_endpoint_but_local_port_stays_fixed(self):
        for service in ('code-server', 'sshd'):
            with self.subTest(service=service):
                occupied = socket.socket()
                occupied.bind(('127.0.0.1', 0))
                occupied.listen()
                self.addCleanup(occupied.close)
                initial = occupied.getsockname()[1]
                self.mock('hostname', 'echo r3n11')
                self.env.update(JOB_ID='123', T4_CODE_PORT=str(initial))
                fake = self.bin/'fake-server'
                fake.write_text('#!'+sys.executable+"\n" + r'''import errno, os, socket, sys, time
args=sys.argv[1:]
service=os.environ['TEST_SERVICE']
port=int(args[args.index('--bind-addr')+1].split(':')[-1]) if service=='code-server' else int(args[args.index('-p')+1])
with open(os.environ['HOME']+'/attempts', 'a') as f: f.write(str(port)+'\n')
s=socket.socket()
try:
    s.bind(('127.0.0.1', port))
except OSError as e:
    message=('EADDRINUSE: address already in use 0.0.0.0:%d' % port if service=='code-server' else 'Bind to port %d on 0.0.0.0 failed: Address already in use' % port)
    print(message if e.errno==errno.EADDRINUSE else str(e), flush=True)
    sys.exit(1)
s.listen()
time.sleep(.3)
print('HTTP server listening on http://0.0.0.0:%d/' % port if service=='code-server' else 'Server listening on 0.0.0.0 port %d.' % port, flush=True)
while True:
    conn, _=s.accept()
    conn.sendall(b'owned by test server')
    conn.close()
''')
                fake.chmod(0o755)
                self.env.update(T4_CODE_SERVER=str(fake), TEST_SERVICE=service)
                if service=='code-server':
                    command=[str(ROOT/'remote/start-code-server')]
                else:
                    command=['bash', '-c', 'source "$1"; compute_node; serve sshd "$2" "$3"',
                             'test', str(ROOT/'lib/common.sh'), str(initial), str(fake)]
                proc=subprocess.Popen(command, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.addCleanup(self.stop_process, proc)
                state=self.wait_state(proc, service)
                chosen=int(state[1])
                self.assertGreater(chosen, initial)
                with socket.create_connection(('127.0.0.1', chosen), timeout=2) as conn:
                    self.assertEqual(conn.recv(100), b'owned by test server')
                self.env['TEST_STATE']=' '.join(state)
                local_command='local/t4-forward' if service=='code-server' else 'local/t4-shell'
                self.assertEqual(self.run_cmd(local_command).returncode, 0)
                args=(self.home/'ssh.log').read_text()
                expected=f'127.0.0.1:8890:r3n11:{chosen}' if service=='code-server' else f'-p\n{chosen}\n'
                self.assertIn(expected, args)
                self.stop_process(proc)
                self.assertFalse((self.home/'.local/state/t4-connection'/service).exists())
                occupied.close()

    def test_collision_retries_are_bounded(self):
        self.mock('hostname', 'echo r3n11')
        self.mock('code-server', 'echo attempt >> "$HOME/attempts"; echo "EADDRINUSE 0.0.0.0:${4##*:}" >&2; exit 1')
        self.env.update(JOB_ID='123', T4_PORT_ATTEMPTS='2')
        result=self.run_cmd('remote/start-code-server')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len((self.home/'attempts').read_text().splitlines()), 2)
        self.assertFalse((self.home/'.local/state/t4-connection/code-server').exists())

    def test_port_upper_bound_and_non_collision_error(self):
        self.mock('hostname', 'echo r3n11')
        self.mock('code-server', 'echo attempt >> "$HOME/attempts"; echo "EADDRINUSE 0.0.0.0:${4##*:}" >&2; exit 1')
        self.env.update(JOB_ID='123', T4_CODE_PORT='65535')
        self.assertNotEqual(self.run_cmd('remote/start-code-server').returncode, 0)
        self.assertEqual(len((self.home/'attempts').read_text().splitlines()), 1)
        (self.home/'attempts').unlink()
        self.mock('code-server', 'echo attempt >> "$HOME/attempts"; echo "EADDRINUSE /tmp/unrelated-ipc.sock" >&2; exit 42')
        self.assertEqual(self.run_cmd('remote/start-code-server').returncode, 42)
        self.assertEqual(len((self.home/'attempts').read_text().splitlines()), 1)

    def test_no_state_without_listening_confirmation(self):
        self.mock('hostname', 'echo r3n11')
        self.mock('code-server', 'exec sleep 30')
        self.env.update(JOB_ID='123', T4_STARTUP_TIMEOUT='1')
        result=self.run_cmd('remote/start-code-server')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No listening confirmation', result.stderr)
        self.assertFalse((self.home/'.local/state/t4-connection/code-server').exists())
        self.assertFalse((self.home/'.local/state/t4-connection/code-server.lock').exists())

    def test_install_preserves_symlink_target_and_runs_commands(self):
        target = self.home/'.local/bin/t4-shell'
        target.parent.mkdir(parents=True)
        original = self.home/'original'
        original.write_text('keep me')
        target.symlink_to(original)
        result = self.run_cmd('local/install')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(original.read_text(), 'keep me')
        self.assertFalse(target.is_symlink())
        self.assertTrue(list(target.parent.glob('t4-shell.before.*')))
        result = subprocess.run([str(target)], env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0)

    def test_service_early_failure_cleans_state(self):
        self.mock('hostname', 'echo r3n11')
        self.mock('code-server', 'exit 42')
        self.env['JOB_ID'] = '123'
        self.assertEqual(self.run_cmd('remote/start-code-server').returncode, 42)
        self.assertFalse((self.home/'.local/state/t4-connection/code-server.lock').exists())


if __name__ == '__main__':
    unittest.main()
