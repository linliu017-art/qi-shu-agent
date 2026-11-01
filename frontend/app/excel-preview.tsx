"use client";
import {useState} from 'react';
import {columnName,officeData,sheetWidth,slidePage} from './lib/office';
import {useApi} from './lib/use-api';
import {ErrorNotice} from './materials';

function excelData(value:unknown){const document=officeData(value);if(document.kind!=='xlsx')throw new Error('该成果不是Excel');return document}
export default function ExcelPreview({id}:{id:string}){
 const [sheetIndex,setSheetIndex]=useState(0);const [page,setPage]=useState(0);const resource=useApi(`/tasks/${encodeURIComponent(id)}/office`,excelData);
 if(resource.error)return <ErrorNotice message={`无法加载工作表：${resource.error}`} retry={resource.reload}/>;
 if(resource.loading||!resource.data)return <p role="status" className="loading">正在加载工作表…</p>;
 const sheets=resource.data.sheets;const sheet=sheets[sheetIndex];if(!sheet)return <p>没有可预览的工作表。</p>;
 const width=sheetWidth(sheet),pages=Math.max(1,Math.ceil(sheet.rows.length/20)),current=Math.min(page,pages-1),rows=sheet.rows.slice(current*20,current*20+20);
 return <section className="excel-preview" aria-label="Excel工作表预览">
  <div className="excel-preview-heading"><label htmlFor="preview-sheet">工作表</label><select id="preview-sheet" value={sheetIndex} onChange={e=>{setSheetIndex(Number(e.target.value));setPage(0)}}>{sheets.map((s,i)=><option key={i} value={i}>{s.name}</option>)}</select></div>
  <div className="excel-preview-scroll" role="region" aria-label="工作表内容" tabIndex={0}><table className="excel-preview-table"><thead><tr><th scope="col">行</th>{Array.from({length:width},(_,i)=><th scope="col" key={i}>{columnName(i)}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={i}><th scope="row">{current*20+i+1}</th>{Array.from({length:width},(_,j)=><td key={j}>{row[j]===null||row[j]===undefined?'':String(row[j])}</td>)}</tr>)}</tbody></table></div>
  {pages>1&&<div className="pagination"><button type="button" disabled={current===0} onClick={()=>setPage(slidePage(current,-1,pages))}>上一页</button><span>第 {current+1} / {pages} 页</span><button type="button" disabled={current===pages-1} onClick={()=>setPage(slidePage(current,1,pages))}>下一页</button></div>}
  <p className="note">显示工作表内容；公式按文字显示，具体格式以下载的 Excel 为准。</p>
 </section>
}
