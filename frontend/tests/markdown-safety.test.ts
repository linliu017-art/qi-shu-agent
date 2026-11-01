import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error Node native TypeScript imports use explicit extension.
import {richAllowed,sameMarkdownMeaning} from '../app/lib/markdown-safety.ts';
test('等价的列表写法可安全转换，文字丢失会被拒绝',()=>{
 assert.equal(sameMarkdownMeaning('# 标题\n\n* 一\n* 二','# 标题\n\n- 一\n- 二'),true);
 assert.equal(sameMarkdownMeaning('# 标题\n\n* 一\n* 二','# 标题\n\n- 一'),false);
});
test('不支持的图片、HTML、脚注和危险链接不进入可视化转换',()=>{
 for(const value of ['![图](x.png)','<div>原文</div>','a[^1]\n\n[^1]: 注释','[链接](javascript:alert)']) assert.equal(richAllowed(value),false,value);
 assert.equal(richAllowed('[文档](https://example.com)'),true);
});
test('转换不应忽略表格对齐或文字格式变化',()=>{
 assert.equal(sameMarkdownMeaning('| 一 | 二 |\n| :--- | ---: |\n| x | y |','| 一 | 二 |\n| --- | --- |\n| x | y |'),false);
 assert.equal(sameMarkdownMeaning('**重要**','重要'),false);
});

test('可视化编辑器的标题、加粗、列表、链接和表格可往返且不丢内容',async()=>{
 const {Editor}=await import('@tiptap/core');const {default:StarterKit}=await import('@tiptap/starter-kit');const {Markdown}=await import('@tiptap/markdown');const {TableKit}=await import('@tiptap/extension-table');
 for(const text of ['# 标题\n\n**重要**，[链接](https://example.com)\n\n- 第一项\n- 第二项','# 表格\n\n| 事项 | 状态 |\n| --- | --- |\n| 预算 | 待定 |']){
  const editor=new Editor({element:null,extensions:[StarterKit,TableKit,Markdown],content:text,contentType:'markdown'});
  try{assert.equal(sameMarkdownMeaning(text,editor.getMarkdown()),true)}finally{editor.destroy()}
 }
});
