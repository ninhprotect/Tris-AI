"""Conservative intent routing; explicit composer actions take precedence."""
import re
from ai.identity import normalized


def media_intent(message: str, action: str = 'auto') -> str | None:
    if action in {'image','gif','video'}:
        return action
    if action != 'auto':
        return None
    text = normalized(message.strip())
    if re.search(r'\b(khong|dung|how|explain|translate|dich|cach|huong dan)\b', text[:50]):
        return None
    text = re.sub(r'^(?:tris[,! ]*|hay |please |ban |giup (?:toi|minh) )+', '', text)
    if re.match(r'^(tao|ve|generate|create|draw|make)\b.{0,45}\b(anh|hinh|image|picture|illustration|gif|video)\b',text):
        return 'video' if re.search(r'\bvideo\b',text[:65]) else 'gif' if re.search(r'\bgif\b',text[:65]) else 'image'
    return None
