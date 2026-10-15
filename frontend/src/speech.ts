/** Conservative VI/EN heuristic; a Vietnamese name must not switch English TTS. */
export function speechLanguage(text: string): 'vi' | 'en' {
  const content = text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/Nguyễn Hải Hà Ninh|Đại học Thủ Dầu Một/gi, ' ');
  const accentedWords = (content.match(/\S*[ăâđêôơưàáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵ]\S*/gi) || [])
    .length;
  const englishWords = (
    content.match(
      /\b(the|this|that|your|you|was|were|with|from|have|has|will|would|should|created|developed|english|let's|hello|please|sentence)\b/gi,
    ) || []
  ).length;
  if (englishWords >= 3 && englishWords > accentedWords) return 'en';
  return accentedWords ? 'vi' : 'en';
}
