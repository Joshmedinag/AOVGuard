from aovguard.io.protocol import EXRReader


def test_exr_reader_protocol_is_importable() -> None:
    assert EXRReader.__name__ == "EXRReader"
