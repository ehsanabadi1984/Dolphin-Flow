import io
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from backup.restore_services import RestoreError
from backup.staged_media_restore import StagedMediaRestore


class StagedMediaRestoreTests(SimpleTestCase):
    def _write_archive(self, path, members):
        with tarfile.open(path, "w:gz") as archive:
            for name, data, kind in members:
                info = tarfile.TarInfo(name)
                if kind == "dir":
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                elif kind == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = "/tmp/outside"
                    archive.addfile(info)
                else:
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))

    def test_prepare_extracts_files_without_touching_live_media(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            (root / "existing.txt").write_text("keep")
            archive = Path(temp) / "media.tar.gz"
            self._write_archive(
                archive,
                [
                    ("uploads", b"", "dir"),
                    ("uploads/a.txt", b"alpha", "file"),
                    ("nested/b.txt", b"beta", "file"),
                ],
            )

            service = StagedMediaRestore(77, media_root=root)
            stage = service.prepare(archive)

            self.assertTrue((stage / "uploads" / "a.txt").is_file())
            self.assertEqual((stage / "uploads" / "a.txt").read_bytes(), b"alpha")
            self.assertEqual(service.file_count, 2)
            self.assertEqual(service.total_bytes, 9)
            self.assertEqual((root / "existing.txt").read_text(), "keep")
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["existing.txt"])
            self.assertEqual(stage.parent, root.parent)
            self.assertEqual(stage.stat().st_dev, root.parent.stat().st_dev)

            service.cleanup()
            self.assertFalse(stage.exists())
            self.assertEqual((root / "existing.txt").read_text(), "keep")

    def test_stage_path_callback_runs_before_directory_creation(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            archive = Path(temp) / "media.tar.gz"
            self._write_archive(archive, [("a.txt", b"a", "file")])
            observed = {}

            def record_stage_path(path):
                observed["path"] = path
                observed["exists_before_creation"] = path.exists()

            service = StagedMediaRestore(
                82, media_root=root, on_stage_created=record_stage_path
            )
            stage = service.prepare(archive)

            self.assertEqual(observed["path"], stage)
            self.assertFalse(observed["exists_before_creation"])
            self.assertTrue(stage.is_dir())
            service.cleanup()

    def test_cleanup_does_not_remove_unowned_path_when_creation_collides(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            archive = Path(temp) / "media.tar.gz"
            self._write_archive(archive, [("a.txt", b"a", "file")])
            unowned = {}

            def occupy_intended_path(path):
                path.mkdir()
                (path / "keep.txt").write_text("not mine")
                unowned["path"] = path

            service = StagedMediaRestore(
                83, media_root=root, on_stage_created=occupy_intended_path
            )
            with self.assertRaises(RestoreError):
                service.prepare(archive)

            self.assertEqual((unowned["path"] / "keep.txt").read_text(), "not mine")
            self.assertIsNone(service.stage_dir)

    def test_prepare_rejects_path_traversal_and_cleans_stage(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            archive = Path(temp) / "media.tar.gz"
            self._write_archive(archive, [("../escape.txt", b"bad", "file")])

            service = StagedMediaRestore(78, media_root=root)
            with self.assertRaises(RestoreError):
                service.prepare(archive)

            self.assertIsNone(service.stage_dir)
            self.assertEqual(list(Path(temp).glob(".media.restore-*")), [])

    def test_prepare_rejects_duplicate_normalized_paths(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            archive = Path(temp) / "media.tar.gz"
            self._write_archive(
                archive,
                [
                    ("folder/a.txt", b"a", "file"),
                    ("folder//a.txt", b"b", "file"),
                ],
            )

            service = StagedMediaRestore(79, media_root=root)
            with self.assertRaises(RestoreError):
                service.prepare(archive)

            self.assertIsNone(service.stage_dir)

    def test_prepare_rejects_links(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "media"
            root.mkdir()
            archive = Path(temp) / "media.tar.gz"
            self._write_archive(archive, [("link", b"", "symlink")])

            service = StagedMediaRestore(80, media_root=root)
            with self.assertRaises(RestoreError):
                service.prepare(archive)

            self.assertIsNone(service.stage_dir)

    def test_prepare_rejects_media_root_symlink(self):
        with TemporaryDirectory() as temp:
            actual = Path(temp) / "actual"
            actual.mkdir()
            root = Path(temp) / "media"
            root.symlink_to(actual, target_is_directory=True)
            archive = Path(temp) / "media.tar.gz"
            self._write_archive(archive, [("a.txt", b"a", "file")])

            service = StagedMediaRestore(81, media_root=root)
            with self.assertRaises(RestoreError):
                service.prepare(archive)
