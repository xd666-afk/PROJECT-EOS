"""Shared water-surface and river-bank predicates for all building entry points."""


def is_water(tile):
    return (not tile or not tile.get('land') or bool(tile.get('river'))
            or bool(tile.get('lake')) or tile.get('biome') in {'ocean','lake'})


def river_bank(world, coord):
    return not is_water(world.tiles.get(coord)) and any(
        world.tiles.get(p,{}).get('river') for p in world.neighbors(*coord))


def repair_water_placements(state, *, preserve_checkpoint=True):
    """Move legacy facilities to legal dry ground, refund those with no valid site."""
    from copy import deepcopy
    from worldgen import hex_distance
    changes=[]
    for cid,country in state.countries.items():
        occupied=set(country.buildings)|{tuple(p['tile']) for p in country.projects}
        for city in country.cities:
            source=city.center
            if not is_water(state.world.tiles.get(source)):continue
            candidates=[p for p in city.tiles if p in country.tiles and p not in occupied
                        and not is_water(state.world.tiles.get(p)) and not any(c.center==p for c in country.cities)]
            if not candidates:raise ValueError(f'{city.name} 位于水面且没有可迁移的岸上城域')
            target=min(candidates,key=lambda p:(hex_distance(source,p),p[1],p[0]))
            city.center=target;city.zones[target]='residential'
            for army in country.armies:
                if army.tile==source and army.march is None:army.tile=target
            changes.append(dict(country_id=cid,kind='city',city_id=city.city_id,source=list(source),target=list(target)))
        def destination(source,building):
            spec=state.config['buildings'][building]
            candidates=[p for p in country.tiles if p not in occupied and not is_water(state.world.tiles.get(p))
                        and state.world.tile(p)['biome'] in spec['allowed_biomes']
                        and (not spec.get('requires_river') or river_bank(state.world,p))
                        and (not spec.get('on_city_center') or any(c.center==p for c in country.cities))]
            return min(candidates,key=lambda p:(hex_distance(source,p),p[1],p[0])) if candidates else None
        for source,building in list(country.buildings.items()):
            if building=='ROAD' or not is_water(state.world.tiles.get(source)):continue
            target=destination(source,building)
            del country.buildings[source];occupied.discard(source)
            refund=0
            if target is not None:country.buildings[target]=building;occupied.add(target)
            else:
                refund=float(state.config['buildings'][building]['cost']);country.treasury+=refund
            changes.append(dict(country_id=cid,kind='building',building=building,source=list(source),
                                target=list(target) if target is not None else None,refund=refund))
        for project in list(country.projects):
            source=tuple(project['tile']);building=project['building']
            if building=='ROAD' or not is_water(state.world.tiles.get(source)):continue
            target=destination(source,building);occupied.discard(source);refund=0
            if target is not None:project['tile']=target;occupied.add(target)
            else:
                country.projects.remove(project)
                refund=float(project.get('cost',state.config['buildings'][building]['cost']));country.treasury+=refund
            changes.append(dict(country_id=cid,kind='project',project_id=project['project_id'],building=building,
                                source=list(source),target=list(target) if target is not None else None,refund=refund))
        for city in country.cities:
            for coord,zone in list(city.zones.items()):
                if zone!='unzoned' and is_water(state.world.tiles.get(coord)):
                    city.zones[coord]='unzoned'
                    changes.append(dict(country_id=cid,kind='zone',city_id=city.city_id,source=list(coord),previous=zone))
    if changes:
        checkpoint=dict(countries_after=deepcopy({cid:c.to_dict() for cid,c in state.countries.items()}),
                        monthly_ledger=deepcopy(state.monthly_ledger)) if preserve_checkpoint else {}
        state.record('water_placements_repaired',changes=changes,**checkpoint)
    return changes
