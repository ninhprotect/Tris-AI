import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import ts from 'typescript';

const source = await fs.readFile('src/speech.ts', 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const { speechLanguage } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
for (const [text, expected] of [
  ['Hello! I am Tris, your English tutor.', 'en'],
  ['Tris AI was created by Nguyễn Hải Hà Ninh, a student at Đại học Thủ Dầu Một.', 'en'],
  ['Xin chào Ninh. Tris sẽ cùng bạn học tiếng Anh hôm nay.', 'vi'],
  ['Mình được tạo ra bởi Nguyễn Hải Hà Ninh, sinh viên Đại học Thủ Dầu Một.', 'vi'],
  ['Bạn nên dùng thì hiện tại, ví dụ: She goes to school every day.', 'vi'],
  ['Please practice this sentence with your friend from Việt Nam.', 'en'],
]) assert.equal(speechLanguage(text), expected, text);
console.log('6 speech-language assertions passed.');
