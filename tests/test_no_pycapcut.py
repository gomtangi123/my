"""카드뉴스는 pycapcut 없이 돌아야 한다.

이미지만 만드는 기능이 영상 라이브러리를 요구하면, 그것 하나 없다고
`ModuleNotFoundError: No module named 'pycapcut'` 으로 죽는다. 실제로
윈도우에서 그렇게 죽었다. 하위 프로세스에서 임포트를 막아 재현한다.
"""

import subprocess
import sys
import textwrap

import pytest

BLOCK = textwrap.dedent(
    '''
    import sys

    class Blocker:
        """pycapcut 이 안 깔린 PC 를 흉내 낸다."""

        def find_spec(self, name, path=None, target=None):
            if name == "pycapcut" or name.startswith("pycapcut."):
                raise ImportError("pycapcut is blocked for this test")
            return None

    sys.meta_path.insert(0, Blocker())
    for name in [m for m in sys.modules if m.startswith("pycapcut")]:
        del sys.modules[name]
    '''
)


def run(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", BLOCK + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestWithoutPycapcut:
    def test_cli_imports(self):
        out = run("import capcut_auto.cli; print('ok')")
        assert out.returncode == 0, out.stderr
        assert "ok" in out.stdout

    def test_cardnews_package_imports(self):
        out = run("import capcut_auto.cardnews; print('ok')")
        assert out.returncode == 0, out.stderr

    def test_capcut_paths_still_works(self):
        # paths 는 pycapcut 을 안 쓴다. 같이 죽으면 안 된다.
        out = run("from capcut_auto.capcut import paths; paths.candidates(); print('ok')")
        assert out.returncode == 0, out.stderr

    def test_template_error_is_importable(self):
        # main() 의 except 절이 이걸 잡는다. draft 를 통해 가져오면 죽는다.
        out = run("from capcut_auto.capcut.errors import TemplateError; print('ok')")
        assert out.returncode == 0, out.stderr

    def test_cardnews_command_renders(self, tmp_path):
        out = run(
            f"""
            from capcut_auto.cli import main
            code = main([
                "cardnews", "examples/sample.txt",
                "-o", {str(tmp_path)!r},
                "--photos", "off", "-q",
            ])
            print("exit", code)
            """
        )
        if "FontMissing" in out.stderr or "글꼴" in out.stdout:
            pytest.skip("한글 글꼴이 없는 환경")
        assert out.returncode == 0, out.stderr
        assert "exit 0" in out.stdout
        assert sorted(p.name for p in tmp_path.glob("*.png"))[:2] == ["01.png", "02.png"]

    def test_draft_still_fails_loudly(self):
        # 숨기면 안 된다. 드래프트를 실제로 쓰려 할 때는 분명히 터져야 한다.
        out = run("from capcut_auto.capcut import draft")
        assert out.returncode != 0
        assert "pycapcut" in out.stderr
