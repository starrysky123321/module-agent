class PdfDownloadError(RuntimeError):
    """PDF 下载或响应校验失败。"""


class UnsafePdfUrlError(PdfDownloadError):
    """PDF 地址可能访问本机、内网或非 HTTP 服务。"""


class PdfTooLargeError(PdfDownloadError):
    """PDF 大小超过允许的内存上限。"""


class InvalidPdfContentError(PdfDownloadError):
    """下载结果不是有效的 PDF 内容。"""


class PdfParseError(RuntimeError):
    """PDF could not be parsed in the isolated parser process."""


class PdfResourceLimitError(PdfParseError):
    """PDF parsing exceeded a configured content or resource limit."""


class PdfParseTimeoutError(PdfResourceLimitError):
    """PDF parsing exceeded its wall-clock time limit."""
