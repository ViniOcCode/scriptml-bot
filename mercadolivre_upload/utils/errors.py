"""Enhanced error handling and user-friendly error messages."""

from enum import Enum
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


class ErrorCategory(Enum):
    """Categories of errors for better user guidance."""

    AUTHENTICATION = "authentication"
    VALIDATION = "validation"
    NETWORK = "network"
    CONFIGURATION = "configuration"
    FILE_SYSTEM = "file_system"
    API = "api"
    UNKNOWN = "unknown"


class ErrorCode(Enum):
    """Error codes with user-friendly messages."""

    # Authentication errors
    TOKEN_EXPIRED = (
        "AUTH001",
        "Token de autenticação expirado",
        ErrorCategory.AUTHENTICATION,
    )
    TOKEN_INVALID = (
        "AUTH002",
        "Token de autenticação inválido",
        ErrorCategory.AUTHENTICATION,
    )
    OAUTH_FAILED = (
        "AUTH003",
        "Falha na autenticação OAuth",
        ErrorCategory.AUTHENTICATION,
    )

    # Validation errors
    INVALID_SKU = ("VAL001", "SKU inválido ou duplicado", ErrorCategory.VALIDATION)
    INVALID_PRICE = ("VAL002", "Preço inválido", ErrorCategory.VALIDATION)
    MISSING_REQUIRED_FIELD = (
        "VAL003",
        "Campo obrigatório ausente",
        ErrorCategory.VALIDATION,
    )
    INVALID_CATEGORY = ("VAL004", "Categoria não encontrada", ErrorCategory.VALIDATION)
    INVALID_ATTRIBUTE = ("VAL005", "Atributo inválido", ErrorCategory.VALIDATION)

    # Network errors
    CONNECTION_TIMEOUT = ("NET001", "Tempo de conexão esgotado", ErrorCategory.NETWORK)
    CONNECTION_ERROR = ("NET002", "Erro de conexão", ErrorCategory.NETWORK)
    RATE_LIMITED = ("NET003", "Limite de requisições atingido", ErrorCategory.NETWORK)

    # Configuration errors
    CONFIG_NOT_FOUND = (
        "CFG001",
        "Arquivo de configuração não encontrado",
        ErrorCategory.CONFIGURATION,
    )
    CONFIG_INVALID = (
        "CFG002",
        "Arquivo de configuração inválido",
        ErrorCategory.CONFIGURATION,
    )
    MISSING_ENV_VAR = (
        "CFG003",
        "Variável de ambiente ausente",
        ErrorCategory.CONFIGURATION,
    )

    # File system errors
    FILE_NOT_FOUND = ("FS001", "Arquivo não encontrado", ErrorCategory.FILE_SYSTEM)
    DIRECTORY_NOT_FOUND = (
        "FS002",
        "Diretório não encontrado",
        ErrorCategory.FILE_SYSTEM,
    )
    PERMISSION_DENIED = ("FS003", "Permissão negada", ErrorCategory.FILE_SYSTEM)

    # API errors
    API_ERROR = ("API001", "Erro na API do Mercado Livre", ErrorCategory.API)
    CATEGORY_NOT_FOUND = (
        "API002",
        "Categoria não encontrada na API",
        ErrorCategory.API,
    )
    INVALID_IMAGE = ("API003", "Imagem inválida", ErrorCategory.API)

    # Unknown
    UNKNOWN_ERROR = ("UNK001", "Erro desconhecido", ErrorCategory.UNKNOWN)

    def __init__(self, code: str, message: str, category: ErrorCategory):
        """Initialize error code.

        Args:
            code: Error code string
            message: Default error message
            category: Error category
        """
        self.code = code
        self.default_message = message
        self.category = category


class EnhancedError(Exception):
    """Enhanced error with user-friendly messaging."""

    def __init__(
        self,
        error_code: ErrorCode,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        suggestion: str | None = None,
    ):
        """Initialize enhanced error.

        Args:
            error_code: Error code enum
            message: Optional custom message
            details: Optional error details
            suggestion: Optional user suggestion
        """
        self.error_code = error_code
        self.message = message or error_code.default_message
        self.details = details or {}
        self.suggestion = suggestion or self._get_default_suggestion()
        super().__init__(self.message)

    def _get_default_suggestion(self) -> str:
        """Get default suggestion based on error category."""
        suggestions = {
            ErrorCategory.AUTHENTICATION: (
                "Execute o comando 'ml-upload doctor' para verificar a autenticação.\n"
                "Se necessário, delete o arquivo tokens.json e execute o upload novamente."
            ),
            ErrorCategory.VALIDATION: (
                "Verifique os dados do produto no arquivo Excel.\n"
                "Execute 'ml-upload validate --detailed' para mais detalhes."
            ),
            ErrorCategory.NETWORK: (
                "Verifique sua conexão com a internet.\n"
                "Se o problema persistir, aguarde alguns minutos e tente novamente."
            ),
            ErrorCategory.CONFIGURATION: (
                "Verifique se o arquivo .env está configurado corretamente.\n"
                "Execute 'ml-upload doctor' para diagnosticar problemas."
            ),
            ErrorCategory.FILE_SYSTEM: (
                "Verifique se os caminhos dos arquivos estão corretos.\n"
                "Execute 'ml-upload doctor --fix' para corrigir problemas automáticos."
            ),
            ErrorCategory.API: (
                "Verifique se os dados estão corretos.\n"
                "Consulte a documentação da API do Mercado Livre."
            ),
            ErrorCategory.UNKNOWN: (
                "Entre em contato com o suporte se o problema persistir.\n"
                "Execute com --verbose para obter mais detalhes técnicos."
            ),
        }
        return suggestions.get(self.error_code.category, "")

    def display(self, console: Console | None = None):  # type: ignore[no-untyped-def]
        """Display error in a user-friendly format."""
        console = console or Console()

        # Error header
        header = Text()
        header.append(f"[{self.error_code.code}] ", style="bold red")
        header.append(self.message, style="red")

        # Build content
        content_parts = [header]

        # Add details if available
        if self.details:
            content_parts.append(Text())
            content_parts.append(Text("Detalhes:", style="bold"))
            for key, value in self.details.items():
                content_parts.append(Text(f"  • {key}: {value}", style="dim"))

        # Add suggestion
        if self.suggestion:
            content_parts.append(Text())
            content_parts.append(Text("Sugestão:", style="bold yellow"))
            content_parts.append(Text(self.suggestion, style="yellow"))

        # Create panel
        content = Text.assemble(*content_parts)
        panel = Panel(
            content,
            title="[bold red]Erro[/bold red]",
            border_style="red",
        )

        console.print(panel)


def classify_exception(exception: Exception) -> EnhancedError:
    """Classify a standard exception into an EnhancedError."""
    error_msg = str(exception).lower()

    # Check for specific error patterns
    if "token" in error_msg or "auth" in error_msg:
        return EnhancedError(ErrorCode.TOKEN_INVALID, details={"original": str(exception)})

    if "timeout" in error_msg:
        return EnhancedError(ErrorCode.CONNECTION_TIMEOUT, details={"original": str(exception)})

    if "connection" in error_msg:
        return EnhancedError(ErrorCode.CONNECTION_ERROR, details={"original": str(exception)})

    if "file not found" in error_msg or "no such file" in error_msg:
        return EnhancedError(ErrorCode.FILE_NOT_FOUND, details={"original": str(exception)})

    if "permission" in error_msg:
        return EnhancedError(ErrorCode.PERMISSION_DENIED, details={"original": str(exception)})

    if "category" in error_msg:
        return EnhancedError(ErrorCode.CATEGORY_NOT_FOUND, details={"original": str(exception)})

    if "validation" in error_msg:
        return EnhancedError(ErrorCode.INVALID_ATTRIBUTE, details={"original": str(exception)})

    if "rate limit" in error_msg or "429" in error_msg:
        return EnhancedError(ErrorCode.RATE_LIMITED, details={"original": str(exception)})

    # Default to unknown
    return EnhancedError(ErrorCode.UNKNOWN_ERROR, message=str(exception))


def format_validation_errors(errors: list[str]) -> str:
    """Format validation errors for display."""
    if not errors:
        return ""

    formatted = []
    for error in errors:
        # Try to extract SKU and error message
        if ":" in error:
            parts = error.split(":", 1)
            sku = parts[0].strip()
            msg = parts[1].strip()
            formatted.append(f"[bold]{sku}[/bold]: {msg}")
        else:
            formatted.append(error)

    return "\n".join(formatted)


def create_summary_table(
    published: int,
    failed: int,
    fiscal_success: int = 0,
    fiscal_failed: int = 0,
) -> Table:
    """Create a summary table for results."""
    from rich.table import Table

    table = Table(show_header=True, header_style="bold")
    table.add_column("Métrica", style="cyan")
    table.add_column("Valor", justify="right")
    table.add_column("Status", justify="center")

    total = published + failed

    # Published
    status = "✓" if published > 0 else "•"
    style = "success" if published > 0 else "dim"
    table.add_row("Publicados", str(published), Text(status, style=style))

    # Failed
    status = "✗" if failed > 0 else "•"
    style = "error" if failed > 0 else "dim"
    table.add_row("Falhas", str(failed), Text(status, style=style))

    # Total
    table.add_row("Total", str(total), "•", style="dim")

    # Fiscal data
    if fiscal_success > 0 or fiscal_failed > 0:
        table.add_row("")
        status = "✓" if fiscal_success > 0 else "•"
        style = "success" if fiscal_success > 0 else "dim"
        table.add_row("Fiscal Enviado", str(fiscal_success), Text(status, style=style))

        status = "✗" if fiscal_failed > 0 else "•"
        style = "error" if fiscal_failed > 0 else "dim"
        table.add_row("Fiscal Falhou", str(fiscal_failed), Text(status, style=style))

    return table
