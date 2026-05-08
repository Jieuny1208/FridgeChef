"""JSON Schema for recipe-generation responses (PRD Step 2 §5.4)."""

DIFFICULTY_VALUES = ["쉬움", "보통", "어려움"]

RECIPE_SCHEMA = {
    "$schema": "https://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["recipes"],
    "additionalProperties": True,
    "properties": {
        "recipes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "title",
                    "summary",
                    "estimated_minutes",
                    "difficulty",
                    "servings",
                    "ingredients_used",
                    "steps",
                ],
                "additionalProperties": True,
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "summary": {"type": "string", "minLength": 1},
                    "estimated_minutes": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 240,
                    },
                    "difficulty": {"type": "string", "enum": DIFFICULTY_VALUES},
                    "servings": {"type": "integer", "minimum": 1, "maximum": 20},
                    "ingredients_used": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["name", "amount"],
                            "additionalProperties": True,
                            "properties": {
                                "name": {"type": "string", "minLength": 1},
                                "amount": {"type": "string", "minLength": 1},
                                "from_fridge": {"type": "boolean"},
                            },
                        },
                    },
                    "extra_ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "amount"],
                            "additionalProperties": True,
                            "properties": {
                                "name": {"type": "string", "minLength": 1},
                                "amount": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                    "steps": {
                        "type": "array",
                        "minItems": 3,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "tips": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            },
        }
    },
}
