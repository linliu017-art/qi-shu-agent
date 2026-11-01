import {unified} from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';

type Node={type:string;value?:string;depth?:number;ordered?:boolean;start?:number|null;checked?:boolean|null;url?:string;title?:string|null;lang?:string|null;meta?:string|null;align?:Array<string|null>;children?:Node[]};
const parser=unified().use(remarkParse).use(remarkGfm);
const unsupported=new Set(['html','image','imageReference','definition','linkReference','footnoteDefinition','footnoteReference','yaml','math']);
function parse(text:string):Node{return parser.parse(text) as Node}
function allowed(node:Node):boolean{
 if(unsupported.has(node.type)||node.checked!=null)return false;
 if(node.type==='link'&&node.url&&!/^(https?:|mailto:|\/|#)/i.test(node.url))return false;
 return !node.children||node.children.every(allowed);
}
function semantic(node:Node):unknown{
 const result:Record<string,unknown>={type:node.type};
 for(const name of ['value','depth','ordered','start','checked','url','title','lang','meta','align'] as const){const value=node[name];if(value!==undefined&&value!==null)result[name]=value}
 if(node.children)result.children=node.children.map(semantic);
 return result;
}
export function richAllowed(text:string):boolean{try{return allowed(parse(text))}catch{return false}}
export function sameMarkdownMeaning(before:string,after:string):boolean{
 try{const one=parse(before),two=parse(after);return allowed(one)&&allowed(two)&&JSON.stringify(semantic(one))===JSON.stringify(semantic(two))}catch{return false}
}
