import time
from collections.abc import Callable
from typing import Protocol, TypeVar

from gisting.agent.assemble import Loaded
from gisting.agent.identity import model_identity
from gisting.manifest.record import GistManifest
from gisting.model_server.config import ModelConfig
from gisting.model_server.interface import Model
from gisting.prompt.tokenizer import PromptTokenizer
from gisting.serve.config import LIMITS, Limits, ServeEnv
from gisting.serve.lookup_client import Boundable, client_factory
from gisting.serve.runner import LookupParts
from gisting.shopify.http_transport import HttpConfig, HttpTransport
from gisting.tools.cache import InMemoryOrderCache
from gisting.tools.policy import load_policy

T = TypeVar("T")
TRANSPORT_ATTEMPTS = 1
TransportFactory = Callable[[str, HttpConfig], Boundable]


class LoadError(Exception):
    def __init__(self, message: str, inner_type: str | None = None) -> None:
        super().__init__(message)
        self.inner_type = inner_type


class GistView(Protocol):
    @property
    def count(self) -> int: ...


class LoadedModel(Model, Protocol):
    @property
    def gist(self) -> GistView | None: ...

    @property
    def gist_manifest(self) -> GistManifest | None: ...

    def without_gist(self) -> "LoadedModel": ...


ModelLoader = Callable[[ModelConfig], tuple[LoadedModel, PromptTokenizer]]


def transformers_loader(config: ModelConfig) -> tuple[LoadedModel, PromptTokenizer]:
    from gisting.model_server.transformers_backend import TransformersModel

    model = TransformersModel.load(config, config.gist_dir)
    return model, PromptTokenizer.from_dir(config.model_dir)


def guarded(step: str, build: Callable[[], T]) -> T:
    try:
        return build()
    except LoadError:
        raise
    except Exception as error:  # noqa: BLE001
        inner_type = type(error).__name__
        message = f"{step} failed: {inner_type}"
        raise LoadError(message, inner_type) from None


def pair_from(
    model: LoadedModel, tokenizer: PromptTokenizer, config: ModelConfig
) -> tuple[Loaded, Loaded]:
    gist, manifest = model.gist, model.gist_manifest
    if gist is None or manifest is None:
        message = "the model loaded without its gist artifact"
        raise LoadError(message)
    with_gist = Loaded(
        model, tokenizer, gist.count, manifest.run_id, model_identity(config.model_dir, manifest)
    )
    without = Loaded(
        model.without_gist(), tokenizer, identity=model_identity(config.model_dir, None)
    )
    return with_gist, without


def load_models(env: ServeEnv, load: ModelLoader = transformers_loader) -> tuple[Loaded, Loaded]:
    config = ModelConfig(env.model_dir, env.device, env.gist_dir)

    def build() -> tuple[Loaded, Loaded]:
        model, tokenizer = load(config)
        return pair_from(model, tokenizer, config)

    return guarded("model load", build)


def build_transport(
    secret: str, limits: Limits = LIMITS, make: TransportFactory = HttpTransport
) -> Boundable:
    config = HttpConfig(
        timeout=limits.shopify_timeout_s,
        query_attempts=TRANSPORT_ATTEMPTS,
        max_wait_seconds=limits.shopify_max_pause_s,
    )
    return make(secret, config)


def load_lookup(
    env: ServeEnv,
    limits: Limits = LIMITS,
    make: TransportFactory = HttpTransport,
    sleep: Callable[[float], None] = time.sleep,
) -> LookupParts:
    def build() -> LookupParts:
        transport = build_transport(env.shopify_secret, limits, make)
        policy = load_policy()
        clients = client_factory(
            transport, sleep, limits.shopify_read_attempts, limits.shopify_retry_s
        )
        cache = InMemoryOrderCache(policy.cache_ttl_seconds)
        return LookupParts(clients, cache, policy, env.email_secret)

    return guarded("lookup assembly", build)
