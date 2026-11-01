"use client";
import {useEffect,useRef,useState} from 'react';
import {EditorContent,useEditor} from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import {Markdown} from '@tiptap/markdown';
import {TableKit} from '@tiptap/extension-table';
import {richAllowed,sameMarkdownMeaning} from './lib/markdown-safety';

type Props={content:string;disabled:boolean;onChange:(value:string)=>void};
export default function RichEditor({content,disabled,onChange}:Props){
 const [source,setSource]=useState(false);const [safe,setSafe]=useState<boolean|null>(null);const original=useRef(content);const last=useRef(content);const ready=useRef(false);
 const editor=useEditor({immediatelyRender:false,extensions:[StarterKit.configure({link:{openOnClick:false}}),TableKit,Markdown],content:richAllowed(content)?content:'',contentType:'markdown',editable:!disabled,
  editorProps:{attributes:{'aria-label':'成果正文编辑','aria-multiline':'true',role:'textbox'}},
  onCreate:({editor})=>{const valid=richAllowed(content)&&sameMarkdownMeaning(content,editor.getMarkdown());ready.current=valid;setSafe(valid)},
  onUpdate:({editor})=>{if(!ready.current)return;const markdown=editor.getMarkdown();const next=sameMarkdownMeaning(original.current,markdown)?original.current:markdown;if(next!==last.current){last.current=next;onChange(next)}}
 });
 useEffect(()=>{editor?.setEditable(!disabled)},[editor,disabled]);
 function changeMode(){
  if(source||safe===false){if(!editor)return;const acceptable=richAllowed(content);if(acceptable){last.current=content;editor.commands.setContent(content,{contentType:'markdown',emitUpdate:false});const valid=sameMarkdownMeaning(content,editor.getMarkdown());ready.current=valid;setSafe(valid)}else{ready.current=false;setSafe(false)};setSource(false)}
  else setSource(true);
 }
 const showSource=source||safe===false;
 return <div className="rich-editor">
  <div className="editor-mode"><label id="rich-label">成果正文</label><button type="button" className="quiet" onClick={changeMode} disabled={disabled}>{showSource?'尝试可视化编辑':'查看原文'}</button></div>
  {safe===false&&<p className="notice" role="status">这份内容包含暂不支持直接排版编辑的格式。为保留原文，请在下方编辑原始内容；保存前可以退出，不会改变原稿。</p>}
  {showSource?<textarea id="artifact-text" className="editor-text" aria-label="成果正文原文" maxLength={100000} value={content} disabled={disabled} onChange={e=>{last.current=e.target.value;onChange(e.target.value)}}/>:safe===null?<p role="status">正在准备编辑器…</p>:<>
   <div className="rich-toolbar" role="toolbar" aria-label="文本格式">
    <button type="button" disabled={disabled} onClick={()=>editor?.chain().focus().setParagraph().run()}>正文</button>
    <button type="button" disabled={disabled} onClick={()=>editor?.chain().focus().toggleHeading({level:2}).run()}>标题</button>
    <button type="button" disabled={disabled} onClick={()=>editor?.chain().focus().toggleBold().run()}><strong>加粗</strong></button>
    <button type="button" disabled={disabled} onClick={()=>editor?.chain().focus().toggleItalic().run()}><em>斜体</em></button>
    <button type="button" disabled={disabled} onClick={()=>editor?.chain().focus().toggleBulletList().run()}>项目列表</button>
    <button type="button" disabled={disabled} onClick={()=>editor?.chain().focus().toggleOrderedList().run()}>编号列表</button>
    <button type="button" disabled={disabled} onClick={()=>editor?.chain().focus().toggleBlockquote().run()}>引用</button>
    <button type="button" disabled={disabled} onClick={()=>editor?.chain().focus().undo().run()}>撤销</button>
    <button type="button" disabled={disabled} onClick={()=>editor?.chain().focus().redo().run()}>重做</button>
   </div>
   <EditorContent editor={editor} className="rich-surface" />
   <p className="note">直接点击正文或表格单元格修改；保存后可下载 Word。</p>
  </>}
 </div>
}
