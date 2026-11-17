/* Render the server-owned bounded parameter schema without evaluating code. */
export function mountOperationFields(parent,fields,overrides={}){
  const controls=new Map();
  for(const spec of fields||[]){
    const label=document.createElement('label');label.textContent=spec.label;
    const control=document.createElement(spec.field_type==='select'?'select':spec.field_type==='textarea'?'textarea':'input');
    control.setAttribute('aria-label',spec.label);control.name=spec.key;
    if(spec.field_type==='select')for(const item of spec.options||[]){const option=document.createElement('option');option.value=String(item.value);option.textContent=item.label;control.append(option);}
    else if(spec.field_type==='number'){control.type='number';for(const key of ['min','max','step'])if(spec[key]!=null)control[key]=spec[key];}
    else if(spec.field_type==='boolean')control.type='checkbox';
    else control.type='text';
    const value=overrides[spec.key]??spec.default_value??'';
    if(spec.field_type==='boolean')control.checked=Boolean(value);else control.value=String(value);
    control.required=Boolean(spec.required);if(spec.max_length)control.maxLength=spec.max_length;
    label.append(control);parent.append(label);controls.set(spec.key,{control,spec});
  }
  return {
    value(key,fallback=null){const entry=controls.get(key);if(!entry)return fallback;const {control,spec}=entry;return spec.field_type==='number'?Number(control.value):spec.field_type==='boolean'?control.checked:control.value;},
    valid(){for(const {control,spec}of controls.values()){const raw=control.value,value=Number(raw);if(spec.field_type==='number'&&(raw===''||!Number.isFinite(value)||(spec.min!=null&&value<spec.min)||(spec.max!=null&&value>spec.max)||(spec.step===1&&!Number.isInteger(value))))return false;}return true;},
  };
}
