def generate_venue_name_candidates(name: str | None) -> list[str]:
    """生成用于别名匹配的会议期刊名称候选。"""
    if name is None or not name.strip():
        return []
    normalized_name = " ".join(name.split())
    result = []
    
    result.append(normalized_name)
    
    if normalized_name.startswith("Proceedings of the "):
        normalized_name = normalized_name.removeprefix("Proceedings of the ").strip()
        result.append(normalized_name)  
    elif normalized_name.startswith("Proceedings of "):
        normalized_name = normalized_name.removeprefix("Proceedings of ").strip()
        result.append(normalized_name)  
    
    return result
