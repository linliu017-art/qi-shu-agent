export type Cell = string | number | boolean | null;
export type Sheet = {name:string;rows:Cell[][]};
export type Slide = {title:string;body:string[]};
export type OfficeDocument = {kind:'xlsx'|'pptx';title:string;sheets:Sheet[];slides:Slide[]};
function object(value:unknown):Record<string,unknown>{if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('办公成果格式异常');return value as Record<string,unknown>}
export function officeData(value:unknown):OfficeDocument{
 const data=object(object(value).document);
 if((data.kind!=='xlsx'&&data.kind!=='pptx')||typeof data.title!=='string'||!Array.isArray(data.sheets)||!Array.isArray(data.slides))throw new Error('办公成果格式异常');
 const sheets=data.sheets.map((item:unknown)=>{const row=object(item);if(typeof row.name!=='string'||!Array.isArray(row.rows)||!row.rows.every((cells:unknown)=>Array.isArray(cells)&&cells.every((v:unknown)=>v===null||['string','number','boolean'].includes(typeof v))))throw new Error('工作表格式异常');return {name:row.name,rows:row.rows as Cell[][]}});
 const slides=data.slides.map((item:unknown)=>{const row=object(item);if(typeof row.title!=='string'||!Array.isArray(row.body)||!row.body.every((v:unknown)=>typeof v==='string'))throw new Error('幻灯片格式异常');return {title:row.title,body:row.body as string[]}});
 if((data.kind==='xlsx'&&(!sheets.length||slides.length))||(data.kind==='pptx'&&(!slides.length||sheets.length)))throw new Error('办公成果格式异常');
 return {kind:data.kind,title:data.title,sheets,slides};
}
export function updateCell(document:OfficeDocument,sheet:number,row:number,column:number,value:Cell):OfficeDocument{
 return {...document,sheets:document.sheets.map((s,i)=>i!==sheet?s:{...s,rows:s.rows.map((r,j)=>{if(j!==row)return r;const cells=[...r];while(cells.length<=column)cells.push(null);cells[column]=value;return cells})})};
}
export function updateSlide(document:OfficeDocument,index:number,field:'title'|'body',value:string,position=0):OfficeDocument{
 return {...document,slides:document.slides.map((s,i)=>i!==index?s:field==='title'?{...s,title:value}:{...s,body:s.body.map((v,j)=>j===position?value:v)})};
}
export function columnName(index:number):string{let name='';for(let n=index+1;n>0;n=Math.floor((n-1)/26))name=String.fromCharCode(65+(n-1)%26)+name;return name}

function sheetAt(document:OfficeDocument,index:number):Sheet{const sheet=document.kind==='xlsx'?document.sheets[index]:undefined;if(!sheet)throw new Error('工作表不存在');return sheet}
function replaceSheet(document:OfficeDocument,index:number,sheet:Sheet):OfficeDocument{return {...document,sheets:document.sheets.map((old,i)=>i===index?sheet:old)}}
export function sheetWidth(sheet:Sheet):number{return Math.max(...sheet.rows.map(row=>row.length))}
export function appendRow(document:OfficeDocument,index:number):OfficeDocument{
 const sheet=sheetAt(document,index);if(sheet.rows.length>=1000)throw new Error('每个工作表最多1000行');
 return replaceSheet(document,index,{...sheet,rows:[...sheet.rows,Array<Cell>(sheetWidth(sheet)).fill(null)]});
}
export function removeRow(document:OfficeDocument,index:number,row:number):OfficeDocument{
 const sheet=sheetAt(document,index);if(sheet.rows.length<=1)throw new Error('工作表至少保留一行');if(row<0||row>=sheet.rows.length)throw new Error('行不存在');
 return replaceSheet(document,index,{...sheet,rows:sheet.rows.filter((_,i)=>i!==row)});
}
export function appendColumn(document:OfficeDocument,index:number):OfficeDocument{
 const sheet=sheetAt(document,index),width=sheetWidth(sheet);if(width>=50)throw new Error('每个工作表最多50列');
 return replaceSheet(document,index,{...sheet,rows:sheet.rows.map(row=>[...row,...Array<Cell>(width-row.length).fill(null),null])});
}
export function removeColumn(document:OfficeDocument,index:number,column:number):OfficeDocument{
 const sheet=sheetAt(document,index),width=sheetWidth(sheet);if(width<=1)throw new Error('工作表至少保留一列');if(column<0||column>=width)throw new Error('列不存在');
 return replaceSheet(document,index,{...sheet,rows:sheet.rows.map(row=>{const next=row.filter((_,i)=>i!==column);return next.length?next:[null]})});
}
export function numericPositions(document:OfficeDocument):string[]{const out:string[]=[];document.sheets.forEach((sheet,i)=>sheet.rows.forEach((row,j)=>row.forEach((value,k)=>{if(typeof value==='number')out.push(`${i}:${j}:${k}`)})));return out}
export function removeNumericPosition(keys:string[],sheet:number,axis:'row'|'column',index:number):string[]{
 return keys.flatMap(key=>{const [s,r,c]=key.split(':').map(Number);if(s!==sheet)return [key];const n=axis==='row'?r:c;if(n===index)return [];return [`${s}:${axis==='row'&&n>index?r-1:r}:${axis==='column'&&n>index?c-1:c}`]});
}
export function addSlide(document:OfficeDocument):OfficeDocument{if(document.kind!=='pptx')throw new Error('不是PPT成果');if(document.slides.length>=30)throw new Error('最多支持30页');return {...document,slides:[...document.slides,{title:'',body:['']}]}}
export function removeSlide(document:OfficeDocument,index:number):OfficeDocument{if(document.kind!=='pptx'||index<0||index>=document.slides.length)throw new Error('页面不存在');if(document.slides.length<=1)throw new Error('至少保留一页');return {...document,slides:document.slides.filter((_,i)=>i!==index)}}
export function moveSlide(document:OfficeDocument,index:number,direction:-1|1):OfficeDocument{const target=index+direction;if(document.kind!=='pptx'||index<0||index>=document.slides.length||target<0||target>=document.slides.length)throw new Error('无法移动页面');const slides=[...document.slides];[slides[index],slides[target]]=[slides[target],slides[index]];return {...document,slides}}

export function pptPreviewData(value:unknown):OfficeDocument{const doc=officeData(value);if(doc.kind!=='pptx')throw new Error('该成果不是PPT');return doc}
export function pptBodyFontSize(slide:Slide):number{return slide.body.reduce((sum,line)=>sum+Math.ceil([...line].length/40),0)<=10?18:14}
export function slidePage(index:number,delta:number,total:number):number{return Math.min(Math.max(index+delta,0),Math.max(0,total-1))}
