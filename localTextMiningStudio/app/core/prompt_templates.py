"""Prompt template management."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, SchemaError

from app.utils.paths import get_settings_dir


DEFAULT_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "resources" / "prompts"
USER_PROMPTS_DIR_NAME = "prompts"

PROMPT_TEMPLATE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "system_prompt": {"type": "string", "minLength": 1},
        "user_prompt_template": {"type": "string", "minLength": 1},
        "allowed_entity_types": {"type": "array", "items": {"type": "string"}},
        "recommended_relations": {"type": "array", "items": {"type": "string"}},
        "output_schema": {"type": "object"}
    },
    "required": [
        "name",
        "description",
        "system_prompt",
        "user_prompt_template",
        "allowed_entity_types",
        "recommended_relations",
        "output_schema"
    ],
    "additionalProperties": False
}


class PromptTemplateError(Exception):
    """Raised when prompt templates cannot be loaded or saved."""


@dataclass(frozen=True)
class PromptTemplate:
    """A validated prompt template."""

    name: str
    description: str
    system_prompt: str
    user_prompt_template: str
    allowed_entity_types: list[str]
    recommended_relations: list[str]
    output_schema: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PromptTemplate":
        validate_template_data(data)
        return cls(
            name=data["name"],
            description=data["description"],
            system_prompt=data["system_prompt"],
            user_prompt_template=data["user_prompt_template"],
            allowed_entity_types=list(data["allowed_entity_types"]),
            recommended_relations=list(data["recommended_relations"]),
            output_schema=dict(data["output_schema"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PromptTemplateManager:
    """Load and manage built-in and user-edited prompt templates."""

    def __init__(
        self,
        default_dir: Path | None = None,
        user_dir: Path | None = None,
    ) -> None:
        self.default_dir = default_dir or DEFAULT_PROMPTS_DIR
        self.user_dir = user_dir or get_settings_dir() / USER_PROMPTS_DIR_NAME
        self.user_dir.mkdir(parents=True, exist_ok=True)

    def list_templates(self) -> list[PromptTemplate]:
        templates: dict[str, PromptTemplate] = {}
        for path in sorted(self.default_dir.glob("*.json")):
            template = self.load_from_file(path)
            templates[template.name] = template
        for path in sorted(self.user_dir.glob("*.json")):
            template = self.load_from_file(path)
            templates[template.name] = template
        return sorted(templates.values(), key=lambda template: template.name)

    def get_template(self, name: str) -> PromptTemplate:
        for template in self.list_templates():
            if template.name == name:
                return template
        raise PromptTemplateError(f"未找到模板：{name}")

    def copy_template(self, source_name: str, new_name: str) -> PromptTemplate:
        source = self.get_template(source_name)
        data = source.to_dict()
        data["name"] = new_name
        data["description"] = f"{source.description}（副本）"
        template = PromptTemplate.from_dict(data)
        self.save_template(template)
        return template

    def save_template(self, template: PromptTemplate) -> Path:
        validate_template_data(template.to_dict())
        path = self.user_dir / f"{slugify(template.name)}.json"
        path.write_text(
            json.dumps(template.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def restore_defaults(self) -> None:
        if self.user_dir.exists():
            shutil.rmtree(self.user_dir)
        self.user_dir.mkdir(parents=True, exist_ok=True)

    def import_template(self, source_path: Path | str) -> PromptTemplate:
        template = self.load_from_file(Path(source_path))
        self.save_template(template)
        return template

    def export_template(self, template_name: str, output_path: Path | str) -> Path:
        template = self.get_template(template_name)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(template.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def load_from_file(self, path: Path) -> PromptTemplate:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            raise PromptTemplateError(f"读取模板失败：{path.name}：{error}") from error
        try:
            return PromptTemplate.from_dict(data)
        except PromptTemplateError:
            raise
        except Exception as error:
            raise PromptTemplateError(f"模板格式错误：{path.name}：{error}") from error


def validate_template_data(data: dict[str, Any]) -> None:
    errors = sorted(Draft202012Validator(PROMPT_TEMPLATE_SCHEMA).iter_errors(data), key=str)
    if errors:
        message = "; ".join(error.message for error in errors[:3])
        raise PromptTemplateError(f"模板 JSON Schema 校验失败：{message}")

    output_schema = data.get("output_schema", {})
    try:
        Draft202012Validator.check_schema(output_schema)
    except SchemaError as error:
        raise PromptTemplateError(f"output_schema 不是有效 JSON Schema：{error.message}") from error


def slugify(name: str) -> str:
    slug = re.sub(r"\s+", "_", name.strip())
    slug = re.sub(r'[<>:"/\\|?*]+', "_", slug)
    return slug.strip("._") or "prompt_template"
