from app.tools.adapters.fastembed_sparse import FastEmbedSparseEncoder


class FakeSparseResult:
    """测试用 FastEmbed sparse 输出对象。"""

    def __init__(self, indices, values) -> None:
        self.indices = indices
        self.values = values


class FakeFastEmbedModel:
    """测试用 FastEmbed 模型。"""

    def __init__(self, result=None, should_raise: bool = False) -> None:
        self.result = result or FakeSparseResult([2, "4"], [0.5, "1.25"])
        self.should_raise = should_raise
        self.calls = []

    def embed(self, texts):
        """记录输入文本并返回可迭代 sparse 结果。"""
        self.calls.append(texts)
        if self.should_raise:
            raise RuntimeError("encode failed")
        return iter([self.result])


class RaisingFactory:
    """测试用异常 FastEmbed 工厂。"""

    def __call__(self, model_name: str):
        raise RuntimeError(f"load failed: {model_name}")


class RecordingFactory:
    """测试用记录模型名的 FastEmbed 工厂。"""

    def __init__(self) -> None:
        self.model_names = []

    def __call__(self, model_name: str):
        self.model_names.append(model_name)
        return FakeFastEmbedModel()


def test_fastembed_sparse_encoder_uses_default_model_name() -> None:
    """FastEmbed sparse 适配器应在模型名为空时使用默认 BM25。"""
    factory = RecordingFactory()

    encoder = FastEmbedSparseEncoder(model_factory=factory)

    assert encoder.model_name == "Qdrant/bm25"
    assert factory.model_names == ["Qdrant/bm25"]


def test_fastembed_sparse_encoder_converts_object_output() -> None:
    """FastEmbed sparse 适配器应转换对象输出为 Qdrant sparse dict。"""
    model = FakeFastEmbedModel(FakeSparseResult([2, "4"], [0.5, "1.25"]))
    encoder = FastEmbedSparseEncoder(model_name="Qdrant/bm42", model=model)

    vector = encoder.encode("创造性")

    assert vector == {"indices": [2, 4], "values": [0.5, 1.25]}
    assert model.calls == [["创造性"]]


def test_fastembed_sparse_encoder_converts_dict_output() -> None:
    """FastEmbed sparse 适配器应转换 dict 输出为 Qdrant sparse dict。"""
    model = FakeFastEmbedModel({"indices": [7], "values": [0.75]})
    encoder = FastEmbedSparseEncoder(model=model)

    assert encoder.encode("新颖性") == {"indices": [7], "values": [0.75]}


def test_fastembed_sparse_encoder_returns_empty_when_model_load_fails() -> None:
    """FastEmbed 模型加载失败时应降级为空 sparse 向量。"""
    encoder = FastEmbedSparseEncoder(model_factory=RaisingFactory())

    assert encoder.encode("创造性") == {"indices": [], "values": []}


def test_fastembed_sparse_encoder_returns_empty_when_encode_fails() -> None:
    """FastEmbed 编码失败时应降级为空 sparse 向量。"""
    encoder = FastEmbedSparseEncoder(model=FakeFastEmbedModel(should_raise=True))

    assert encoder.encode("创造性") == {"indices": [], "values": []}
