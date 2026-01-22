import os
import json
import time
import logging
from ml_api import MLAPI

logger = logging.getLogger(__name__)

CACHE_DIR = "cache"
CACHE_TTL = 86400  # 24 hours in seconds


def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)


def get_cached_category(api: MLAPI, category_id: str):
    """
    Get category details from cache or fetch from API if expired/missing.
    """
    ensure_cache_dir()
    cache_file = os.path.join(CACHE_DIR, f"{category_id}.json")

    # Check cache
    if os.path.exists(cache_file):
        file_age = time.time() - os.path.getmtime(cache_file)
        if file_age < CACHE_TTL:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    logger.debug(f"Cache hit for category {category_id}")
                    return json.load(f)
            except Exception as e:
                logger.warning(
                    f"Failed to read cache for {category_id}, re-fetching: {e}"
                )

    # Fetch from API
    logger.info(f"Fetching category rules for {category_id}...")
    data = api.get_category(category_id)

    # Save to cache
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to write cache for {category_id}: {e}")

    return data


def map_simple_attributes(item: dict):
    """
    Map simple keys (brand, model, etc.) to the 'attributes' list structure.
    """
    # Map friendly names to Attribute IDs
    MAPPING = {
        "brand": "BRAND",
        "model": "MODEL",
        "ean": "GTIN",  # GTIN is the standard ID for EAN/UPC
        "color": "COLOR",
        "size": "SIZE",
        "gender": "GENDER",
    }

    if "attributes" not in item:
        item["attributes"] = []

    # Track existing IDs to avoid duplicates
    existing_ids = {attr["id"] for attr in item["attributes"]}

    for friendly_key, attr_id in MAPPING.items():
        if friendly_key in item:
            value = item.pop(friendly_key)  # Remove the simple key
            if value and attr_id not in existing_ids:
                item["attributes"].append({"id": attr_id, "value_name": str(value)})
                existing_ids.add(attr_id)

    return item


def auto_fill_defaults(item: dict, category_data: dict):
    """
    Auto-fill missing required attributes with safe defaults where permitted.
    """
    if "attributes" not in item:
        item["attributes"] = []

    existing_ids = {attr["id"] for attr in item["attributes"]}

    # List of attributes we can try to autofill
    # In a real scenario, you'd check category_data["attributes"] to see what is required
    # For now, we apply common defaults if they are missing

    # 1. Brand -> Generic
    if "BRAND" not in existing_ids:
        # Check if BRAND is required for this category
        brand_req = False
        for attr in category_data.get("attributes", []):
            if attr["id"] == "BRAND" and "required" in str(attr.get("tags")):
                brand_req = True
                break

        if brand_req:
            logger.info(f"Auto-filling missing BRAND for '{item.get('title')}'")
            item["attributes"].append({"id": "BRAND", "value_name": "Genérica"})
            existing_ids.add("BRAND")

    return item


def auto_fill_shipping(item: dict):
    """
    Auto-fill shipping details to comply with mandatory free shipping rules.
    """
    if "shipping" not in item:
        item["shipping"] = {}

    # Default to "me2" (Mercado Envios 2) which is the standard for most sellers in Brazil.
    # "not_specified" was causing issues as it still triggered ME1 checks.
    if "mode" not in item["shipping"]:
        item["shipping"]["mode"] = "me2"

    # Enable local pickup as fallback (safe default)
    if "local_pick_up" not in item["shipping"]:
        item["shipping"]["local_pick_up"] = False

    # Mandatory Free Shipping Rule for Brazil (Items >= 79 BRL)
    # Note: This threshold can change, but 79 is the current standard.
    try:
        price = float(item.get("price", 0))
        if price >= 79:
            item["shipping"]["free_shipping"] = True
    except (ValueError, TypeError):
        pass  # Ignore if price is invalid (will be caught by main validator)

    return item


def get_cached_attributes(api: MLAPI, category_id: str):
    """
    Get category attributes from cache or fetch from API if expired/missing.
    Returns a list of attribute definitions including which are required.
    """
    ensure_cache_dir()
    cache_file = os.path.join(CACHE_DIR, f"{category_id}_attributes.json")

    # Check cache
    if os.path.exists(cache_file):
        file_age = time.time() - os.path.getmtime(cache_file)
        if file_age < CACHE_TTL:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    logger.debug(f"Cache hit for attributes of {category_id}")
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read attribute cache for {category_id}: {e}")

    # Fetch from API
    data = api.get_category_attributes(category_id)

    # Save to cache
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to write attribute cache for {category_id}: {e}")

    return data


def get_required_attributes(api: MLAPI, category_id: str):
    """
    Returns a list of required attribute IDs for a category.
    """
    attributes = get_cached_attributes(api, category_id)
    required = []

    for attr in attributes:
        tags = attr.get("tags", {})

        # Check if required
        is_required = False
        if isinstance(tags, dict):
            is_required = tags.get("required", False)
        elif isinstance(tags, list):
            is_required = "required" in tags

        if is_required:
            required.append(
                {
                    "id": attr["id"],
                    "name": attr.get("name", attr["id"]),
                    "value_type": attr.get("value_type", "string"),
                    "values": attr.get(
                        "values", []
                    ),  # Allowed values if it's a list type
                }
            )

    return required


def check_missing_attributes(item: dict, api: MLAPI, category_id: str):
    """
    Check which required attributes are missing from an item.
    Returns a list of missing attribute definitions.
    """
    required = get_required_attributes(api, category_id)

    # Get existing attribute IDs from item
    existing_ids = set()
    for attr in item.get("attributes", []):
        existing_ids.add(attr.get("id"))

    # Find missing
    missing = []
    for req in required:
        if req["id"] not in existing_ids:
            missing.append(req)

    return missing


def print_missing_attributes_report(item: dict, api: MLAPI, category_id: str):
    """
    Print a helpful report of missing required attributes for an item.
    """
    missing = check_missing_attributes(item, api, category_id)

    if not missing:
        return

    print(
        f"\n   [!] Missing {len(missing)} required attribute(s) for category {category_id}:"
    )
    for attr in missing:
        values_hint = ""
        if attr["values"]:
            # Show first 3 allowed values as hint
            sample_values = [v.get("name", v.get("id")) for v in attr["values"][:3]]
            values_hint = f" (e.g., {', '.join(sample_values)})"
        print(f"       - {attr['id']}: {attr['name']}{values_hint}")


# =============================================================================
# SMART AUTO-FILL SYSTEM
# =============================================================================

# Global defaults for common attributes (applies to most categories)
GLOBAL_SMART_DEFAULTS = {
    # Brand/Manufacturer
    "BRAND": "Genérica",
    "MANUFACTURER": None,  # Special: copy from BRAND if not set
    # Boolean defaults (most common safe values)
    "IS_DUAL_SIM": "Não",
    "IS_GAMING_CELLPHONE": "Não",
    "IS_RUGGED_CELLPHONE": "Não",
    "IS_GAMER": "Não",
    "IS_ERGONOMIC": "Não",
    "IS_SWIVEL": "Não",
    "REQUIRES_ASSEMBLY": "Não",
    "INCLUDES_ASSEMBLY_MANUAL": "Não",
    "IS_FOLDABLE": "Não",
    "HAS_MEMORY_CARD_SLOT": "Não",
    "IS_WIRELESS": "Não",
    "IS_RECHARGEABLE": "Não",
    "WITH_BLUETOOTH": "Não",
    "WITH_NFC": "Não",
    "WITH_WIFI": "Não",
    "IS_WATERPROOF": "Não",
    "IS_PORTABLE": "Sim",  # Most small electronics are portable
    # Carrier (unlocked is safest)
    "CARRIER": "Desbloqueado",
    # Sale condition
    "SALE_FORMAT": "Unidade",
    "UNITS_PER_PACK": "1",
    "UNITS_PER_PACKAGE": "1",
    # Origin (safe default for Brazil)
    "ORIGIN": "Nacional",
    "ITEM_CONDITION": "Novo",
}

# Attributes that should copy from another attribute if not set
COPY_MAPPINGS = {
    "MANUFACTURER": "BRAND",  # If MANUFACTURER missing, use BRAND
    "ALPHANUMERIC_MODELS": "MODEL",  # If ALPHANUMERIC_MODELS missing, use MODEL
    "ALPHANUMERIC_MODEL": "MODEL",  # Same as above (singular form)
    "LINE": "MODEL",  # Sometimes LINE can be inferred from MODEL
}

# Attributes that CANNOT be auto-filled (require real data)
NEVER_AUTO_FILL = {
    "GTIN",  # Real barcode required
    "CELLPHONES_ANATEL_HOMOLOGATION_NUMBER",  # Government certification
    "ANATEL_HOMOLOGATION_NUMBER",  # Government certification
    "INMETRO_CERTIFICATION",  # Government certification
    "ELECTRICAL_SAFETY_CERTIFICATE_NUMBER",  # Certification
    "SEC_STAMP",  # Picture ID
    "CELLPHONE_PORTABILITY_LABEL",  # Picture ID
    "PACKAGE_HEIGHT",  # Actual measurement
    "PACKAGE_WIDTH",  # Actual measurement
    "PACKAGE_LENGTH",  # Actual measurement
    "PACKAGE_WEIGHT",  # Actual measurement
    "SIZE_GRID_ID",  # Fashion size grid - complex system
    "SIZE",  # Requires real size value
}

# Attributes that can be auto-generated from title
AUTO_GENERATE_FROM_TITLE = {
    "MODEL",  # Generate model name from title
    "ALPHANUMERIC_MODEL",  # Same as MODEL
    "ALPHANUMERIC_MODELS",  # Same as MODEL
}

# Category-specific overrides (category_id -> attribute_id -> value)
CATEGORY_SPECIFIC_DEFAULTS = {
    # Cellphones (MLB1055)
    "MLB1055": {
        "CARRIER": "Desbloqueado",
        "IS_DUAL_SIM": "Sim",  # Most modern phones are dual SIM
    },
    # Notebooks/Laptops
    "MLB1648": {
        "IS_PORTABLE": "Sim",
        "WITH_WIFI": "Sim",
        "WITH_BLUETOOTH": "Sim",
    },
    # TVs
    "MLB1002": {
        "IS_SMART_TV": "Sim",
    },
    # Headphones
    "MLB3697": {
        "IS_WIRELESS": "Sim",  # Most modern headphones
    },
}


def _get_existing_attr_ids(item: dict) -> set:
    """Get set of attribute IDs already present in item."""
    return {attr.get("id") for attr in item.get("attributes", [])}


def _get_attr_value(item: dict, attr_id: str) -> str | None:
    """Get the value of an attribute from item, if present."""
    for attr in item.get("attributes", []):
        if attr.get("id") == attr_id:
            return attr.get("value_name") or attr.get("value_id")
    return None


def _add_attribute(item: dict, attr_id: str, value: str):
    """Add an attribute to item if not already present."""
    if "attributes" not in item:
        item["attributes"] = []

    existing = {a.get("id") for a in item["attributes"]}
    if attr_id not in existing:
        item["attributes"].append({"id": attr_id, "value_name": str(value)})
        return True
    return False


def _infer_from_title(item: dict, attr_def: dict) -> str | None:
    """
    Try to infer attribute value from item title.
    Returns a value if inference is confident, None otherwise.
    """
    title = item.get("title", "").lower()
    attr_id = attr_def.get("id")

    # Color inference from title
    if attr_id == "COLOR" or attr_id == "MAIN_COLOR":
        color_keywords = {
            "preto": "Preto",
            "black": "Preto",
            "branco": "Branco",
            "white": "Branco",
            "azul": "Azul",
            "blue": "Azul",
            "vermelho": "Vermelho",
            "red": "Vermelho",
            "verde": "Verde",
            "green": "Verde",
            "amarelo": "Amarelo",
            "yellow": "Amarelo",
            "rosa": "Rosa",
            "pink": "Rosa",
            "cinza": "Cinza",
            "gray": "Cinza",
            "grey": "Cinza",
            "prata": "Prateado",
            "silver": "Prateado",
            "prateado": "Prateado",
            "dourado": "Dourado",
            "gold": "Dourado",
            "ouro": "Dourado",
            "laranja": "Laranja",
            "orange": "Laranja",
            "roxo": "Violeta",
            "purple": "Violeta",
            "violeta": "Violeta",
            "marrom": "Marrom",
            "brown": "Marrom",
            "bege": "Bege",
            "beige": "Bege",
            "titanio": "Cinza",  # Titanium is usually grayish
            "inox": "Prateado",  # Stainless steel is silver
        }
        for keyword, color_value in color_keywords.items():
            if keyword in title:
                return color_value

    # Gender inference from title (Portuguese)
    if attr_id == "GENDER":
        # Check masculine first (more specific words)
        masc_keywords = [
            "masculino",
            "masculina",
            "homem",
            "homens",
            "menino",
            "meninos",
            "garoto",
        ]
        for kw in masc_keywords:
            if kw in title:
                return "Masculino"
        # Check feminine
        fem_keywords = [
            "feminino",
            "feminina",
            "mulher",
            "mulheres",
            "menina",
            "meninas",
            "garota",
        ]
        for kw in fem_keywords:
            if kw in title:
                return "Feminino"
        # Check unisex
        unisex_keywords = ["unissex", "unisex", "universal"]
        for kw in unisex_keywords:
            if kw in title:
                return "Sem gênero"

    # Dual SIM inference
    if attr_id == "IS_DUAL_SIM":
        if "dual sim" in title or "dual-sim" in title or "dualsim" in title:
            return "Sim"

    # Wireless inference
    if attr_id == "IS_WIRELESS":
        if (
            "wireless" in title
            or "sem fio" in title
            or "bluetooth" in title
            or "bt" in title
        ):
            return "Sim"

    # Gamer inference
    if attr_id == "IS_GAMER":
        if "gamer" in title or "gaming" in title:
            return "Sim"

    # Voltage inference
    if attr_id == "VOLTAGE":
        if "bivolt" in title or "bi-volt" in title:
            return "Bivolt"
        elif "110v" in title or "110 v" in title:
            return "110V"
        elif "220v" in title or "220 v" in title:
            return "220V"

    # Fan type inference
    if attr_id == "FAN_TYPE":
        if "coluna" in title or "torre" in title:
            return "De coluna"
        elif "mesa" in title or "portatil" in title:
            return "De mesa"
        elif "parede" in title:
            return "De parede"
        elif "teto" in title:
            return "De teto"
        elif "pe" in title or "pé" in title or "chao" in title:
            return "De pé"

    # Connector type inference for cables
    if attr_id in ["INPUT_CONNECTOR", "OUTPUT_CONNECTOR", "CONNECTOR_TYPE"]:
        if (
            "tipo c" in title
            or "type c" in title
            or "usb-c" in title
            or "usb c" in title
        ):
            return "USB-C"
        elif "micro usb" in title or "micro-usb" in title:
            return "Micro-USB"
        elif "lightning" in title:
            return "Lightning"
        elif "usb" in title:
            return "USB"

    # Backpack type inference
    if attr_id == "BACKPACK_TYPE":
        if "escolar" in title:
            return "Escolar"
        elif "notebook" in title or "laptop" in title:
            return "Para notebook"
        elif "viagem" in title:
            return "De viagem"
        elif "esportiva" in title or "academia" in title:
            return "Esportiva"

    # Cooking system inference
    if attr_id == "COOKING_SYSTEM":
        if "pressao" in title or "pressão" in title:
            return "A pressão"
        elif "vapor" in title:
            return "A vapor"

    # Product type for pans
    if attr_id == "PRODUCT_TYPE":
        if "frigideira" in title:
            return "Frigideira"
        elif "panela" in title:
            return "Panela"
        elif "bistequeira" in title:
            return "Bistequeira"
        elif "wok" in title:
            return "Wok"

    # Brush type inference
    if attr_id == "BRUSH_TYPE":
        if "secadora" in title:
            return "Secadora"  # Use simple value, ML might not accept combined
        elif "alisadora" in title:
            return "Alisadora"

    # Garment type for clothing
    if attr_id == "GARMENT_TYPE":
        if "camiseta" in title:
            return "Camiseta"
        elif "regata" in title:
            return "Regata"
        elif "camisa" in title:
            return "Camisa"
        elif "blusa" in title:
            return "Blusa"

    # Capacity inference (for thermos, bottles, etc.)
    if attr_id == "THERMO_CAPACITY" or attr_id == "CAPACITY":
        import re

        # Look for patterns like "500ml", "1L", "2 litros"
        ml_match = re.search(r"(\d+)\s*ml", title)
        if ml_match:
            return f"{ml_match.group(1)} ml"
        l_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:l|litro|litros)", title)
        if l_match:
            liters = float(l_match.group(1))
            return (
                f"{int(liters * 1000)} ml" if liters < 10 else f"{l_match.group(1)} L"
            )

    return None


def _get_first_allowed_value(attr_def: dict) -> str | None:
    """
    Get the first allowed value from attribute definition.
    Useful for list-type attributes where we need a valid option.
    """
    values = attr_def.get("values", [])
    if values:
        # Prefer common "default-like" values
        preferred = ["Não", "Desbloqueado", "Unidade", "Nacional", "Genérica", "Outro"]
        for pref in preferred:
            for v in values:
                if v.get("name") == pref:
                    return pref
        # Otherwise return first value
        return values[0].get("name") or values[0].get("id")
    return None


def _generate_model_from_title(title: str) -> str:
    """
    Generate a model name from the item title.
    Takes the first 2-3 significant words or alphanumeric codes.
    """
    import re

    # Words to exclude (common filler words in Portuguese product titles)
    exclude_words = {
        "para",
        "com",
        "sem",
        "kit",
        "conjunto",
        "jogo",
        "unidade",
        "unidades",
        "peca",
        "pecas",
        "peça",
        "peças",
        "novo",
        "nova",
        "original",
        "universal",
        "alta",
        "qualidade",
        "premium",
        "profissional",
        "super",
        "ultra",
        "mega",
        "mini",
        "grande",
        "pequeno",
        "pequena",
        "medio",
        "media",
        "medio",
        "média",
        "preto",
        "branco",
        "azul",
        "vermelho",
        "verde",
        "amarelo",
        "rosa",
        "cinza",
        "dourado",
        "prateado",
        "prata",
        "ouro",
        "bivolt",
        "110v",
        "220v",
        "12v",
        "masculino",
        "feminino",
        "masculina",
        "feminina",
        "infantil",
        "adulto",
    }

    # Clean and split title
    words = title.split()
    significant_words = []

    for word in words:
        # Clean word
        clean_word = word.strip(",-()[]").lower()

        # Skip excluded words and very short words
        if clean_word in exclude_words or len(clean_word) < 2:
            continue

        # Keep alphanumeric model codes (e.g., "A01", "UN55CU7700", "i5-1235U")
        if re.match(r"^[a-z0-9]+[-_]?[a-z0-9]*$", clean_word, re.IGNORECASE):
            significant_words.append(word)
        # Keep brand-like words (capitalized)
        elif word[0].isupper():
            significant_words.append(word)
        # Keep any word with numbers (model numbers)
        elif any(c.isdigit() for c in word):
            significant_words.append(word)

        # Stop after finding enough words
        if len(significant_words) >= 3:
            break

    # If we didn't find significant words, take first 2-3 words
    if not significant_words:
        significant_words = [w for w in words[:3] if len(w) > 2]

    # Join and return (max 60 chars to be safe)
    model = " ".join(significant_words[:3])
    if len(model) > 60:
        model = model[:57] + "..."

    return model if model else "Modelo Generico"


def auto_fill_smart(item: dict, api: MLAPI, category_id: str) -> tuple[dict, list]:
    """
    Intelligently auto-fill missing required attributes based on:
    1. Global defaults
    2. Category-specific defaults
    3. Title inference
    4. Copy mappings from other attributes
    5. First allowed value for list types

    Returns:
        tuple: (modified_item, list_of_filled_attributes)
    """
    if "attributes" not in item:
        item["attributes"] = []

    filled = []  # Track what we auto-filled
    existing_ids = _get_existing_attr_ids(item)

    # Get all required attributes for this category
    all_attrs = get_cached_attributes(api, category_id)
    required_attrs = []

    for attr in all_attrs:
        tags = attr.get("tags", {})
        is_required = False
        if isinstance(tags, dict):
            is_required = tags.get("required", False)
        elif isinstance(tags, list):
            is_required = "required" in tags

        if is_required:
            required_attrs.append(attr)

    # Process each required attribute
    for attr_def in required_attrs:
        attr_id = attr_def["id"]

        # Skip if already present
        if attr_id in existing_ids:
            continue

        # Skip if in NEVER_AUTO_FILL
        if attr_id in NEVER_AUTO_FILL:
            continue

        value = None
        source = None

        # 1. Try title inference first (highest confidence)
        value = _infer_from_title(item, attr_def)
        if value:
            source = "title"

        # 2. Try copy mappings
        if not value and attr_id in COPY_MAPPINGS:
            source_attr = COPY_MAPPINGS[attr_id]
            source_value = _get_attr_value(item, source_attr)
            if source_value:
                value = source_value
                source = f"copy:{source_attr}"

        # 3. Try category-specific defaults
        if not value and category_id in CATEGORY_SPECIFIC_DEFAULTS:
            cat_defaults = CATEGORY_SPECIFIC_DEFAULTS[category_id]
            if attr_id in cat_defaults:
                value = cat_defaults[attr_id]
                source = "category"

        # 4. Try global defaults
        if not value and attr_id in GLOBAL_SMART_DEFAULTS:
            default = GLOBAL_SMART_DEFAULTS[attr_id]
            if default is not None:
                value = default
                source = "global"
            elif default is None and attr_id in COPY_MAPPINGS:
                # Special case: try copy again for None defaults
                source_attr = COPY_MAPPINGS[attr_id]
                source_value = _get_attr_value(item, source_attr)
                if source_value:
                    value = source_value
                    source = f"copy:{source_attr}"

        # 5. For list-type attributes, try first allowed value
        if not value and attr_def.get("value_type") == "list":
            value = _get_first_allowed_value(attr_def)
            if value:
                source = "list_default"

        # 6. For boolean attributes without a default, default to "Não"
        if not value and attr_def.get("value_type") == "boolean":
            value = "Não"
            source = "boolean_default"

        # 7. Auto-generate MODEL from title if still missing
        if not value and attr_id in AUTO_GENERATE_FROM_TITLE:
            title = item.get("title", "")
            if title:
                value = _generate_model_from_title(title)
                source = "generated"

        # Apply the value if we found one
        if value:
            _add_attribute(item, attr_id, value)
            filled.append(
                {
                    "id": attr_id,
                    "name": attr_def.get("name", attr_id),
                    "value": value,
                    "source": source,
                }
            )
            existing_ids.add(attr_id)

    return item, filled


def print_auto_fill_report(filled: list):
    """Print a report of what was auto-filled."""
    if not filled:
        return

    print(f"\n   [+] Auto-filled {len(filled)} attribute(s):")
    for f in filled:
        source_label = {
            "title": "from title",
            "category": "category default",
            "global": "global default",
            "list_default": "first option",
            "boolean_default": "boolean default",
            "generated": "auto-generated",
        }
        src = f["source"]
        if src.startswith("copy:"):
            src_label = f"copied from {src.split(':')[1]}"
        else:
            src_label = source_label.get(src, src)
        print(f'       - {f["id"]}: "{f["value"]}" ({src_label})')
