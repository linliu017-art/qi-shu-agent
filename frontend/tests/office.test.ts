import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error Native Node TypeScript import.
import {officeData,updateCell,updateSlide,columnName} from '../app/lib/office.ts';
test('编辑Excel一个单元格保留其它工作表、数值、布尔值与原稿',()=>{
 const input={kind:'xlsx',title:'表',sheets:[{name:'数据',rows:[['负责人','预算',true],['小王',23,null]]},{name:'其他',rows:[['原文']]}],slides:[]};
 const doc=officeData({document:input});const changed=updateCell(doc,0,1,0,'小李');
 assert.deepEqual(changed.sheets[0].rows,[['负责人','预算',true],['小李',23,null]]);
 assert.deepEqual(changed.sheets[1],input.sheets[1]);assert.equal(doc.sheets[0].rows[1][0],'小王');
});
test('编辑PPT一条正文保留其它页面和标题',()=>{
 const doc=officeData({document:{kind:'pptx',title:'汇报',sheets:[],slides:[{title:'一',body:['保留','原句']},{title:'二',body:['不变']}]}});
 const changed=updateSlide(doc,0,'body','修改',1);
 assert.deepEqual(changed.slides,[{title:'一',body:['保留','修改']},{title:'二',body:['不变']}]);
 assert.equal(doc.slides[0].body[1],'原句');
});
test('不接受错误的Office结构，列名超过Z时仍正确',()=>{
 assert.throws(()=>officeData({document:{kind:'xlsx',title:'x',sheets:[],slides:[]}}),/格式异常/);
 assert.throws(()=>officeData({document:{kind:'pptx',title:'x',sheets:[],slides:[{title:'x',body:[{}]}]}}),/格式异常/);
 assert.equal(columnName(0),'A');assert.equal(columnName(25),'Z');assert.equal(columnName(26),'AA');assert.equal(columnName(49),'AX');
});

test('增删行列保留其他数据，旧对象不变，并正确调整数字位置',async()=>{
 // @ts-expect-error Node native TypeScript import.
 const {appendRow,appendColumn,removeRow,removeColumn,numericPositions,removeNumericPosition}=await import('../app/lib/office.ts');
 const source=officeData({document:{kind:'xlsx',title:'数据',sheets:[{name:'表1',rows:[['名称','数字'],['甲',42],['短行']]},{name:'表2',rows:[[7]]}],slides:[]}});
 const extended=updateCell(source,0,2,1,'可填入空格');assert.deepEqual(extended.sheets[0].rows[2],['短行','可填入空格']);
 let doc=appendColumn(source,0);assert.deepEqual(doc.sheets[0].rows,[['名称','数字',null],['甲',42,null],['短行',null,null]]);
 doc=appendRow(doc,0);assert.deepEqual(doc.sheets[0].rows[3],[null,null,null]);
 doc=removeRow(doc,0,0);let keys=removeNumericPosition(numericPositions(source),0,'row',0);assert.deepEqual(keys,['0:0:1','1:0:0']);
 doc=removeColumn(doc,0,0);keys=removeNumericPosition(keys,0,'column',0);assert.equal(doc.sheets[0].rows[0][0],42);assert.deepEqual(keys,['0:0:0','1:0:0']);
 assert.deepEqual(doc.sheets[1].rows,[[7]]);assert.deepEqual(source.sheets[0].rows,[['名称','数字'],['甲',42],['短行']]);
});
test('页数和表格最小值受保护，页面操作按顺序保留内容',async()=>{
 // @ts-expect-error Node native TypeScript import.
 const {addSlide,removeSlide,moveSlide,removeRow,removeColumn}=await import('../app/lib/office.ts');
 const sheet=officeData({document:{kind:'xlsx',title:'单格',sheets:[{name:'表',rows:[['保留']]}],slides:[]}});assert.throws(()=>removeRow(sheet,0,0));assert.throws(()=>removeColumn(sheet,0,0));
 const source=officeData({document:{kind:'pptx',title:'汇报',sheets:[],slides:[{title:'第一页',body:['甲']},{title:'第二页',body:['乙']}]}});
 let doc=addSlide(source);assert.equal(doc.slides.length,3);doc=moveSlide(doc,1,-1);assert.deepEqual(doc.slides.map(s=>s.title),['第二页','第一页','']);doc=removeSlide(doc,1);assert.deepEqual(doc.slides.map(s=>s.title),['第二页','']);assert.deepEqual(source.slides.map(s=>s.title),['第一页','第二页']);
 assert.throws(()=>removeSlide({...doc,slides:[doc.slides[0]]},0));assert.throws(()=>moveSlide(doc,0,-1));
});

test('幻灯片翻页不会越界，字号与导出模板相同',async()=>{
 // @ts-expect-error Node native TypeScript import.
 const {pptBodyFontSize,slidePage,pptPreviewData}=await import('../app/lib/office.ts');
 assert.equal(slidePage(0,-1,3),0);assert.equal(slidePage(1,1,3),2);assert.equal(slidePage(2,1,3),2);assert.equal(slidePage(0,1,1),0);
 assert.equal(pptBodyFontSize({title:'x',body:['短文']}),18);assert.equal(pptBodyFontSize({title:'x',body:Array(6).fill('长'.repeat(80))}),14);
 assert.throws(()=>pptPreviewData({document:{kind:'xlsx',title:'x',sheets:[{name:'表',rows:[[1]]}],slides:[]}}),/不是PPT/);
});
