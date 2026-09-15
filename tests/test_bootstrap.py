"""Tests for bootstrapping state into Modal."""

from unittest.mock import patch

from bootstrap import upload_volume


class FakeUpload:
    def __init__(self, volume):
        self.volume = volume

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def put_directory(self, local_path, remote_path):
        self.volume.directories[remote_path] = local_path


class FakeVolume:
    def __init__(self, directories=None):
        self.directories = dict(directories or {})

    def remove_file(self, path, recursive=False):
        if path not in self.directories:
            raise FileNotFoundError(path)
        del self.directories[path]

    def batch_upload(self):
        return FakeUpload(self)


def test_upload_volume_replaces_remote_chroma_database():
    volume = FakeVolume({"/chroma_db": "old_chroma_db"})

    with patch("modal.Volume.from_name", return_value=volume):
        upload_volume("new_chroma_db")

    assert volume.directories == {"/chroma_db": "new_chroma_db"}


def test_upload_volume_seeds_empty_remote_volume():
    volume = FakeVolume()

    with patch("modal.Volume.from_name", return_value=volume):
        upload_volume("chroma_db")

    assert volume.directories == {"/chroma_db": "chroma_db"}
