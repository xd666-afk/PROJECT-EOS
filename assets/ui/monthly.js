/* Explicit presentation adapter: the server retains precise legacy fields for saves/replay. */
function monthlyView(payload){
  if(!payload||payload.time_unit!=='month')return payload;
  const calendar=payload.calendar||{},days=calendar.days||30;
  const aliases={days:'months',days_left:'months_left',remaining_days:'remaining_months',estimated_days:'estimated_months',
    duration_days:'duration_months',total_days:'total_months',capture_tribute_days:'capture_tribute_months',
    day:'month_number',start_day:'start_month',end_day:'end_month',ended_day:'ended_month',created_day:'created_month',days_needed:'months_needed',
    expires_day:'expires_month',resolved_day:'resolved_month',arrival_day:'arrival_month',founded_day:'founded_month',source_day:'source_month',daily:'monthly',maximum_day:'maximum_month_number',tested_day:'tested_month',started_day:'started_month',applied_day:'applied_month'};
  const cityMetrics=['food_output','food_need','food_balance','food_loss','food_imported','food_exported','food_unmet','local_revenue','local_upkeep','local_net'];
  const walk=value=>{
    if(Array.isArray(value))return value.map(walk);
    if(!value||typeof value!=='object')return value;
    const result=Object.fromEntries(Object.entries(value).map(([key,v])=>[key,walk(v)]));
    for(const [key,canonical] of Object.entries(aliases))if(value[canonical]!==undefined)result[key]=value[canonical];
    for(const key of Object.keys(value)){
      if(key.startsWith('daily_')&&value['monthly_'+key.slice(6)]!==undefined)result[key]=value['monthly_'+key.slice(6)];
      if(key.endsWith('_per_day')&&value[key.slice(0,-8)+'_per_month']!==undefined)result[key]=value[key.slice(0,-8)+'_per_month'];
      if(key.endsWith('_date')&&value[key.slice(0,-5)+'_month_date'])result[key]=value[key.slice(0,-5)+'_month_date'];
    }
    if(value.month_date)result.date=value.month_date;
    if(value.monthly_hint)result.hint=value.monthly_hint;
    if(value.monthly_reason_text)result.reason_text=value.monthly_reason_text;
    if(value.elapsed_months!==undefined)result.elapsed=value.elapsed_months;
    if(value.monthly_milestones)result.milestones=value.monthly_milestones;
    if(value.month_chronicle)result.chronicle=value.month_chronicle;
    if(value.monthly_economy){
      result.last_economy=value.monthly_economy;
      result.military_upkeep=value.monthly_economy.military_upkeep??((value.military_upkeep||0)*days);
      for(const city of result.cities||[]){
        const settled=value.monthly_city_economy?.[city.city_id];
        for(const key of cityMetrics)if(typeof city[key]==='number')city[key]=settled?.[key]??city[key]*days;
        city.stock_days=city.food_need>0?city.food_stock/city.food_need:null;
        city.food_self_sufficiency=city.food_need>0?city.food_output/city.food_need:1;
        city.food_status=city.food_balance<0?'缺口':city.food_balance>0?'盈余':'平衡';
      }
    }
    if(value.projects_months)result.projects=value.projects_months;
    return result;
  };
  const result=walk(payload);
  if(result.countries&&typeof payload.day==='number'){
    result.engine_day=payload.day;result.day=calendar.month_number;
    result.date=calendar.label;result.month_days=calendar.days;result.month_number=calendar.month_number;
  }
  return result;
}
