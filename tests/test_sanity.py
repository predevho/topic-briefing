"""프로젝트 기반이 제대로 섰는지만 확인한다. 이후 태스크에서 삭제한다."""


def test_pytest가_동작한다():
    assert True


def test_pipeline_패키지를_import할_수_있다():
    import pipeline
    import pipeline.lib

    assert pipeline is not None
    assert pipeline.lib is not None
