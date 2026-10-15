import { uid, type Chat, type Lang, type Mode } from './types';

export const modeLabel = (mode: Mode, lang: Lang) =>
  ({
    Conversation: lang === 'vi' ? 'Hội thoại' : 'Conversation',
    Grammar: lang === 'vi' ? 'Ngữ pháp' : 'Grammar',
    Vocabulary: lang === 'vi' ? 'Từ vựng' : 'Vocabulary',
    'Role Play': lang === 'vi' ? 'Nhập vai' : 'Role play',
  })[mode];

export const newChat = (demo = false, project = ''): Chat => ({
  id: uid(),
  title: '',
  messages: [],
  draft: '',
  project,
  mode: 'Conversation',
  demo,
  created: new Date().toISOString(),
});
export const sampleAnswer = (lang: Lang) =>
  lang === 'vi'
    ? `Chúng ta bắt đầu từ một câu thật gần gũi nhé.\n\n**“Small steps, every day.”** — Mỗi ngày, một bước nhỏ.\n\nBạn không cần học mọi thứ cùng lúc. Hãy chọn một chủ đề mình thích, viết 2–3 câu bằng tiếng Anh, rồi cùng Tris chỉnh cho tự nhiên hơn.\n\n### Thử một ví dụ\n\n> I usually start my morning with a cup of coffee and a good book.\n\n- **usually**: diễn tả thói quen thường xuyên.\n- **start … with**: bắt đầu một việc bằng điều gì đó.\n- Sau **with**, mình dùng danh từ hoặc cụm danh từ.\n\nBạn thường bắt đầu buổi sáng của mình như thế nào?\n\n*Đây là phản hồi mẫu để trải nghiệm giao diện. Chuyển sang AI local trong menu Tris AI để trò chuyện với model thật.*`
    : `Let's start with something familiar.\n\n**“Small steps, every day.”**\n\nPick a topic you enjoy and write two or three sentences. We can make them sound more natural together.\n\n### A small example\n\n> I usually start my morning with a cup of coffee and a good book.\n\n- **usually** describes a regular habit.\n- **start … with** tells us how an activity begins.\n\nHow do you usually start your morning?\n\n*This is a sample response for trying the interface. Switch to local AI in the Tris AI menu to use your real model.*`;

export function initialChats(): Chat[] {
  const starter = newChat();
  const long = newChat(true, 'Tiếng Anh mỗi ngày');
  long.title = 'Một buổi sáng, một câu chuyện';
  long.messages = Array.from({ length: 7 }, (_, i) => [
    {
      id: uid(),
      role: 'user' as const,
      content: [
        'Mình muốn nói tiếng Anh tự nhiên hơn.',
        'Giải thích giúp mình thì hiện tại đơn nhé.',
        'Cho mình thêm một ví dụ thực tế.',
        'Mình nên luyện mỗi ngày như thế nào?',
        'Có thể cho mình một bảng ghi nhớ?',
        'Cho mình xem một đoạn code ghi chú học tập.',
        'Cảm ơn Tris, bắt đầu nhé!',
      ][i],
    },
    {
      id: uid(),
      role: 'assistant' as const,
      content:
        i === 5
          ? 'Bạn có thể lưu một từ mới mỗi ngày như thế này:\n\n```python\nlearning_journal = {\n    "word": "curiosity",\n    "meaning": "sự tò mò",\n    "example": "Stay curious, keep learning."\n}\n\nprint(learning_journal["example"])\n```\n\nMỗi ví dụ do chính bạn viết sẽ giúp từ vựng dễ nhớ hơn.\n\n*Hội thoại mẫu.*'
          : i === 4
            ? '| Cách dùng | Ví dụ |\n| --- | --- |\n| Thói quen | I read every day. |\n| Sự thật | Water boils at 100°C. |\n| Lịch trình | The class starts at 9. |\n\n*Hội thoại mẫu.*'
            : sampleAnswer('vi'),
      seconds: 3,
    },
  ]).flat();
  const names = [
    'Phân biệt “since” và “for”',
    'Từ vựng trong một quán cà phê',
    'Chuẩn bị cho buổi phỏng vấn',
    'Cách viết email tự nhiên',
    'Kể về chuyến đi của mình',
    'Luyện nói: một ngày của bạn',
    'Những cụm từ mình muốn nhớ',
    'Đọc hiểu cùng Tris',
    '5 phút luyện tập mỗi ngày',
    'Khám phá thì quá khứ',
    'Một lời chào thật tự nhiên',
    'Bắt đầu từ những điều nhỏ',
    'Từ vựng về công nghệ',
    'Học qua những câu chuyện',
    'Luyện tập cách đặt câu hỏi',
    'Cùng nhau ôn lại bài cũ',
  ];
  return [
    starter,
    long,
    ...names.map((title, i) => ({
      ...newChat(true, i % 3 === 0 ? 'Tiếng Anh mỗi ngày' : ''),
      title,
      messages: [
        { id: uid(), role: 'user' as const, content: title },
        { id: uid(), role: 'assistant' as const, content: sampleAnswer('vi'), seconds: 2 },
      ],
    })),
  ];
}
