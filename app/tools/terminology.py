class TerminologyTool:
    """术语查询和规范化工具。

    Args:
        terms: 术语映射表,key 为中文术语,value 为规范译名或标准表达。

    Returns:
        无状态术语查询工具。
    """

    def __init__(self, terms: dict[str, str] | None = None) -> None:
        self.terms = terms or {}

    def normalize(self, text: str) -> dict[str, str]:
        """返回文本命中的术语映射。

        Args:
            text: 待检查文本。

        Returns:
            命中的术语映射字典。
        """
        return {term: value for term, value in self.terms.items() if term in text}
