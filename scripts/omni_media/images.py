# SPDX-License-Identifier: MIT
"""Local image backends for Dxrk Omni.

Two adapters are supported:

* ComfyUI: submit a workflow to ``POST /prompt``, follow progress over
  ``/ws`` when the optional ``websockets`` package is available, and fall back
  to ``GET /history/{prompt_id}`` polling. The generated image is fetched from
  ``GET /view``.
* Stable Diffusion WebUI (AUTOMATIC1111): call ``POST /sdapi/v1/txt2img`` and
  decode the base64 image returned by the API.

Both adapters are deliberately synchronous because the Omni pipeline is
synchronous. They are small, dependency-injected clients so the orchestration
can be tested without a running model server.
"""

from __future__ import annotations

import base64
import copy
import json
import logging
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("dxrk.omni.images")

DEFAULT_NEGATIVE_PROMPT = "text, watermark, logo, low quality, blurry, deformed, extra fingers"
DEFAULT_COMFY_CHECKPOINT = "sd_xl_base_1.0.safetensors"
DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_SDWEBUI_URL = "http://127.0.0.1:7860"


class ImageBackendError(RuntimeError):
    """A local image backend could not produce an image."""


@dataclass(frozen=True, slots=True)
class ImageResult:
    path: Path
    source: str
    error: str = ""


def build_comfy_workflow(
    *,
    prompt: str,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    seed: int = 42,
    width: int = 1080,
    height: int = 1920,
    checkpoint: str = DEFAULT_COMFY_CHECKPOINT,
    steps: int = 28,
    cfg: float = 7.0,
    sampler: str = "euler",
    scheduler: str = "normal",
) -> dict[str, Any]:
    """Return a minimal txt2img ComfyUI API workflow.

    The node ids are stable so a user-provided workflow can reuse them, and
    every value that the pipeline needs to vary is exposed as an argument.
    """

    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["4", 1]},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "dxrk-omni", "images": ["8", 0]},
        },
    }


def apply_workflow_template(
    template: Mapping[str, Any],
    replacements: Mapping[str, Any],
) -> dict[str, Any]:
    """Deep-copy a workflow and substitute ``{{NAME}}`` placeholders.

    Exact placeholders keep the replacement type (so ``{{SEED}}`` becomes an
    int). Embedded placeholders are stringified. The input template is never
    mutated.
    """

    def replace(value: Any) -> Any:
        if isinstance(value, str):
            if value.startswith("{{") and value.endswith("}}"):
                key = value[2:-2]
                if key in replacements:
                    return replacements[key]
            rendered = value
            for key, replacement in replacements.items():
                rendered = rendered.replace("{{" + key + "}}", str(replacement))
            return rendered
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {str(key): replace(item) for key, item in value.items()}
        return value

    return replace(copy.deepcopy(dict(template)))


def _prepare_image_bytes(payload: bytes, dest: Path) -> Path:
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover - optional dependency guard
        dest.write_bytes(payload)
        return dest
    with Image.open(BytesIO(payload)) as image:
        prepared = ImageOps.exif_transpose(image).convert("RGB")
        prepared = ImageOps.fit(prepared, (1080, 1920), method=Image.Resampling.LANCZOS)
        prepared.save(dest, "JPEG", quality=92)
    return dest


@dataclass
class ComfyUIClient:
    base_url: str = DEFAULT_COMFY_URL
    checkpoint: str = DEFAULT_COMFY_CHECKPOINT
    workflow: Mapping[str, Any] | None = None
    timeout: float = 300.0
    poll_interval: float = 1.0
    use_websocket: bool = True
    client: httpx.Client | None = None
    ws_connect: Callable[..., Any] | None = None
    sleep: Callable[[float], None] = time.sleep

    def generate(
        self,
        prompt: str,
        dest: Path,
        *,
        seed: int,
        negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
        width: int = 1080,
        height: int = 1920,
    ) -> ImageResult:
        replacements = {
            "PROMPT": prompt,
            "NEGATIVE_PROMPT": negative_prompt,
            "SEED": seed,
            "WIDTH": width,
            "HEIGHT": height,
            "CHECKPOINT": self.checkpoint,
        }
        if self.workflow is not None:
            workflow = apply_workflow_template(self.workflow, replacements)
        else:
            workflow = build_comfy_workflow(
                prompt=prompt,
                negative_prompt=negative_prompt,
                seed=seed,
                width=width,
                height=height,
                checkpoint=self.checkpoint,
            )
        prompt_id = self._submit(workflow)
        image = self._wait_for_image(prompt_id)
        payload = self._download(image)
        _prepare_image_bytes(payload, dest)
        return ImageResult(dest, "comfyui")

    @contextmanager
    def _http(self) -> Iterator[httpx.Client]:
        if self.client is not None:
            yield self.client
            return
        with httpx.Client(timeout=self.timeout) as client:
            yield client

    def _submit(self, workflow: Mapping[str, Any]) -> str:
        url = self.base_url.rstrip("/") + "/prompt"
        payload = {"prompt": workflow, "client_id": uuid.uuid4().hex}
        try:
            with self._http() as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise ImageBackendError(f"ComfyUI no aceptó el workflow: {exc}") from exc
        node_errors = data.get("node_errors") or {}
        if node_errors:
            raise ImageBackendError(f"ComfyUI node_errors: {node_errors}")
        prompt_id = str(data.get("prompt_id") or "")
        if not prompt_id:
            raise ImageBackendError("ComfyUI no devolvió prompt_id")
        return prompt_id

    def _wait_for_image(self, prompt_id: str) -> dict[str, Any]:
        if self.use_websocket:
            try:
                image = self._wait_over_websocket(prompt_id)
            except Exception as exc:
                logger.debug("ComfyUI WebSocket unavailable (%s); polling history", exc)
            else:
                if image is not None:
                    return image
        return self._poll_history(prompt_id)

    def _wait_over_websocket(self, prompt_id: str) -> dict[str, Any] | None:
        connect = self.ws_connect or self._default_ws_connect()
        if connect is None:
            return None
        ws_base = self.base_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
        url = f"{ws_base}/ws?clientId={uuid.uuid4().hex}"
        image: dict[str, Any] | None = None
        with connect(url, open_timeout=self.timeout, close_timeout=5) as connection:
            for raw in connection:
                message = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                if not isinstance(message, dict):
                    continue
                kind = message.get("type")
                data = message.get("data") or {}
                if kind == "execution_error":
                    raise ImageBackendError(f"ComfyUI execution_error: {data}")
                if kind == "executed" and data.get("prompt_id") == prompt_id:
                    images = (data.get("output") or {}).get("images") or []
                    if images:
                        image = images[0]
                if kind == "executing" and data.get("prompt_id") == prompt_id and data.get("node") is None:
                    break
        return image

    def _default_ws_connect(self) -> Callable[..., Any] | None:
        try:
            from websockets.sync.client import connect
        except ImportError:  # pragma: no cover - optional dependency guard
            return None
        return connect

    def _poll_history(self, prompt_id: str) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + f"/history/{prompt_id}"
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            with self._http() as client:
                response = client.get(url)
                response.raise_for_status()
                data = response.json()
            entry = data.get(prompt_id)
            if isinstance(entry, dict):
                images = _extract_images(entry)
                if images:
                    return images[0]
                status = entry.get("status") or {}
                if status.get("completed") or status.get("status_str") == "success":
                    raise ImageBackendError("ComfyUI terminó sin imágenes")
            self.sleep(self.poll_interval)
        raise ImageBackendError("timeout esperando la imagen de ComfyUI")

    def _download(self, image: Mapping[str, Any]) -> bytes:
        params = {
            "filename": str(image.get("filename", "")),
            "subfolder": str(image.get("subfolder", "")),
            "type": str(image.get("type", "output")),
        }
        if not params["filename"]:
            raise ImageBackendError("ComfyUI devolvió una imagen sin filename")
        url = self.base_url.rstrip("/") + "/view"
        with self._http() as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.content


def _extract_images(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    outputs = entry.get("outputs") or {}
    if not isinstance(outputs, Mapping):
        return images
    for output in outputs.values():
        if isinstance(output, Mapping):
            for image in output.get("images") or []:
                if isinstance(image, Mapping) and image.get("filename"):
                    images.append(dict(image))
    return images


@dataclass
class SDWebUIClient:
    base_url: str = DEFAULT_SDWEBUI_URL
    timeout: float = 300.0
    steps: int = 28
    cfg_scale: float = 7.0
    sampler_name: str = "DPM++ 2M Karras"
    client: httpx.Client | None = None

    def generate(
        self,
        prompt: str,
        dest: Path,
        *,
        seed: int,
        negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
        width: int = 1080,
        height: int = 1920,
    ) -> ImageResult:
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "seed": seed,
            "width": width,
            "height": height,
            "steps": self.steps,
            "cfg_scale": self.cfg_scale,
            "sampler_name": self.sampler_name,
            "batch_size": 1,
            "n_iter": 1,
        }
        url = self.base_url.rstrip("/") + "/sdapi/v1/txt2img"
        try:
            with self._http() as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise ImageBackendError(f"SD WebUI no generó la imagen: {exc}") from exc
        images = data.get("images") or []
        if not images:
            raise ImageBackendError("SD WebUI no devolvió ninguna imagen")
        encoded = str(images[0]).split(",", 1)[-1]
        try:
            raw = base64.b64decode(encoded)
        except Exception as exc:
            raise ImageBackendError(f"SD WebUI devolvió una imagen inválida: {exc}") from exc
        _prepare_image_bytes(raw, dest)
        return ImageResult(dest, "sdwebui")

    @contextmanager
    def _http(self) -> Iterator[httpx.Client]:
        if self.client is not None:
            yield self.client
            return
        with httpx.Client(timeout=self.timeout) as client:
            yield client
