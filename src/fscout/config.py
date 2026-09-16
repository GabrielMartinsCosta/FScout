"""Configuracao central da aplicacao, carregada de variaveis de ambiente ou .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Parametros de execucao. Prefixo de ambiente: FSCOUT_."""

    model_config = SettingsConfigDict(
        env_prefix="FSCOUT_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///data/db/fscout.db"
    # Endereco da API que o painel consome. O painel nao fala com o banco: tudo o que
    # ele mostra passa pelos mesmos endpoints documentados em /docs.
    api_url: str = "http://127.0.0.1:8000"
    statsbomb_base_url: str = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
    # API-Football. A chave vem do .env e nunca do codigo: e credencial pessoal, com cota
    # diaria propria. Vazia significa "nao configurada", e a sondagem avisa em vez de falhar.
    api_football_key: str = ""
    api_football_base_url: str = "https://v3.football.api-sports.io"
    transfermarkt_base_url: str = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data"
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    processed_dir: Path = PROJECT_ROOT / "data" / "processed"
    log_level: str = "INFO"

    # Requisicoes HTTP da ingestao.
    http_timeout_seconds: float = 60.0
    http_max_retries: int = 3

    @property
    def resolved_raw_dir(self) -> Path:
        """Diretório do cache bruto, absoluto mesmo quando configurado como relativo."""
        raw_dir = Path(self.raw_dir)
        return raw_dir if raw_dir.is_absolute() else PROJECT_ROOT / raw_dir

    @property
    def resolved_database_url(self) -> str:
        """Torna caminhos SQLite relativos absolutos, para nao depender do cwd."""
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return self.database_url
        raw_path = self.database_url[len(prefix) :]
        path = Path(raw_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"{prefix}{path}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instancia unica de Settings (cacheada) para todo o processo."""
    return Settings()
