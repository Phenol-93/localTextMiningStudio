import json

import pytest

from app.core.prompt_templates import (
    DEFAULT_PROMPTS_DIR,
    PromptTemplate,
    PromptTemplateError,
    PromptTemplateManager,
    validate_template_data,
)


def test_default_prompt_templates_load_and_validate(tmp_path) -> None:
    manager = PromptTemplateManager(default_dir=DEFAULT_PROMPTS_DIR, user_dir=tmp_path)

    templates = manager.list_templates()
    names = {template.name for template in templates}

    assert len(templates) >= 5
    assert "通用三元组抽取" in names
    assert "学术文献概念关系抽取" in names
    assert all(template.output_schema["type"] == "object" for template in templates)


def test_copy_and_edit_template(tmp_path) -> None:
    manager = PromptTemplateManager(default_dir=DEFAULT_PROMPTS_DIR, user_dir=tmp_path)

    copied = manager.copy_template("通用三元组抽取", "通用三元组抽取-测试副本")
    edited = PromptTemplate.from_dict(
        {
            **copied.to_dict(),
            "description": "edited",
            "recommended_relations": ["测试关系"],
        }
    )
    manager.save_template(edited)

    loaded = manager.get_template("通用三元组抽取-测试副本")
    assert loaded.description == "edited"
    assert loaded.recommended_relations == ["测试关系"]


def test_import_export_and_restore_templates(tmp_path) -> None:
    user_dir = tmp_path / "user"
    export_path = tmp_path / "exported.json"
    import_path = tmp_path / "imported.json"
    manager = PromptTemplateManager(default_dir=DEFAULT_PROMPTS_DIR, user_dir=user_dir)

    manager.export_template("通用三元组抽取", export_path)
    data = json.loads(export_path.read_text(encoding="utf-8"))
    data["name"] = "导入模板测试"
    import_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    imported = manager.import_template(import_path)
    assert imported.name == "导入模板测试"
    assert manager.get_template("导入模板测试").name == "导入模板测试"

    manager.restore_defaults()
    with pytest.raises(PromptTemplateError):
        manager.get_template("导入模板测试")


def test_invalid_prompt_template_schema_raises() -> None:
    with pytest.raises(PromptTemplateError):
        validate_template_data(
            {
                "name": "",
                "description": "bad",
                "system_prompt": "",
                "user_prompt_template": "{text}",
                "allowed_entity_types": [],
                "recommended_relations": [],
                "output_schema": {"type": "not-a-json-schema-type"},
            }
        )
