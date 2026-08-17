#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parent / 'dashboard' / 'index.html'
s = path.read_text(encoding='utf-8')
s = s.replace('品川区・目黒区 / 所有権', '品川区・目黒区・大田区 / 所有権')
if '<option>大田区</option>' not in s:
    s = s.replace('<option>目黒区</option>', '<option>目黒区</option><option>大田区</option>')
path.write_text(s, encoding='utf-8')
print('Ota dashboard UI scope applied')
