"""規則與計分共用例外，避免模組循環依賴。"""
class RuleError(ValueError):
    pass
