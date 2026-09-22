import glob
import itertools
import ntpath

from django.http import HttpResponse, Http404
from django.shortcuts import render

import os, json

from django.utils.html import format_html
from django_tables2 import tables, Column, TemplateColumn, RequestConfig

from accservermanager.settings import CAR_MODEL_TYPES, DATA_DIR, TRACKS
from core.decorators import role_required
from results.parser import parse_session_name


def get_track_name(track_code):
    for code, name in TRACKS:
        if code == track_code:
            return name
    return track_code.replace("_", " ").title()


def get_car_name(car_id):
    for model_id, name in CAR_MODEL_TYPES:
        if model_id == car_id:
            return name
    return "Unknown"


def get_car_class(car_id):
    if car_id >= 80:
        return "GT2"
    elif car_id >= 50:
        return "GT4"
    elif car_id >= 9 and car_id in [9, 28]:
        return "GTC"
    else:
        return "GT3"


def format_time_ms(value):
    if value is None or value == 2147483647:
        return "---"
    s = value // 1000
    m = s // 60
    s %= 60
    ms = value % 1000
    if m == 0:
        return "%02i.%03i" % (s, ms)
    return "%i:%02i.%03i" % (m, s, ms)


def format_gap_seconds(ms_value):
    """Formata gap em segundos com sinal: +1.234s"""
    if ms_value is None:
        return "---"
    seconds = ms_value / 1000.0
    return "+%.3fs" % seconds


def calculate_consistency_metrics(lap_times):
    """Calcula métricas intuitivas de consistência.
    
    Retorna dict com:
    - std_dev: desvio padrão em ms (técnico)
    - avg_gap_from_best: gap médio da melhor volta em ms
    - max_variation: diferença entre pior e melhor volta em ms  
    - consistency_ratio: percentual de consistência (0-100)
    """
    if not lap_times or len(lap_times) < 2:
        return {
            "std_dev": 0,
            "std_dev_formatted": "00.000",
            "avg_gap_from_best": 0,
            "avg_gap_from_best_formatted": "+0.000s",
            "max_variation": 0,
            "max_variation_formatted": "+0.000s",
            "consistency_ratio": 100.0,
            "consistency_ratio_formatted": "100.0%",
        }
    
    fastest = min(lap_times)
    slowest = max(lap_times)
    avg_lap = sum(lap_times) / len(lap_times)
    
    # Desvio padrão
    variance = sum((t - avg_lap) ** 2 for t in lap_times) / len(lap_times)
    std_dev = variance ** 0.5
    
    # Gap médio da melhor volta
    gaps_from_best = [t - fastest for t in lap_times]
    avg_gap_from_best = sum(gaps_from_best) / len(gaps_from_best)
    
    # Variação máxima (range)
    max_variation = slowest - fastest
    
    # Consistency ratio: 100% - coefficient of variation (capped at 0-100)
    # CV = std_dev / mean * 100; consistency = 100 - CV
    if avg_lap > 0:
        cv = (std_dev / avg_lap) * 100
        consistency_ratio = max(0, min(100, 100 - cv))
    else:
        consistency_ratio = 100.0
    
    return {
        "std_dev": std_dev,
        "std_dev_formatted": format_time_ms(int(std_dev)),
        "avg_gap_from_best": avg_gap_from_best,
        "avg_gap_from_best_formatted": format_gap_seconds(avg_gap_from_best),
        "max_variation": max_variation,
        "max_variation_formatted": format_gap_seconds(max_variation),
        "consistency_ratio": consistency_ratio,
        "consistency_ratio_formatted": "%.1f%%" % consistency_ratio,
    }


def calculate_session_stats(leaderboard, all_laps=None):
    if not leaderboard:
        return {}
    
    total_laps = 0
    best_laps = []
    valid_best_laps = []
    
    for entry in leaderboard:
        timing = entry.get("timing", {})
        lap_count = timing.get("lapCount", 0)
        best_lap = timing.get("bestLap", 2147483647)
        total_laps += lap_count
        if best_lap != 2147483647:
            valid_best_laps.append(best_lap)
    
    best_lap_session = min(valid_best_laps) if valid_best_laps else None
    avg_best_lap = sum(valid_best_laps) / len(valid_best_laps) if valid_best_laps else None
    
    p1_time = leaderboard[0].get("timing", {}).get("totalTime", 0) if leaderboard else 0
    p10_time = leaderboard[9].get("timing", {}).get("totalTime", 0) if len(leaderboard) >= 10 else None
    gap_p1_p10 = (p10_time - p1_time) if p10_time and p1_time else None
    
    best_splits = leaderboard[0].get("timing", {}).get("bestSplits", []) if leaderboard else []
    
    best_sectors = [None, None, None]
    for entry in leaderboard:
        splits = entry.get("timing", {}).get("bestSplits", [])
        for i, split in enumerate(splits[:3]):
            if split != 2147483647:
                if best_sectors[i] is None or split < best_sectors[i]:
                    best_sectors[i] = split
    
    # Calcular Best Possible Lap (soma dos melhores setores)
    best_possible_lap = None
    if all(best_sectors):
        best_possible_lap = sum(best_sectors)
    
    stats = {
        "total_drivers": len(leaderboard),
        "total_laps": total_laps,
        "best_lap": best_lap_session,
        "best_lap_formatted": format_time_ms(best_lap_session),
        "avg_best_lap": avg_best_lap,
        "avg_best_lap_formatted": format_time_ms(int(avg_best_lap)) if avg_best_lap else "---",
        "gap_p1_p10": gap_p1_p10,
        "gap_p1_p10_formatted": format_time_ms(gap_p1_p10) if gap_p1_p10 else "---",
        "best_sectors": best_sectors,
        "best_possible_lap": best_possible_lap,
        "best_possible_lap_formatted": format_time_ms(best_possible_lap) if best_possible_lap else "---",
    }
    
    # Estatísticas adicionais se tivermos dados de voltas completas
    if all_laps:
        valid_laps = [l for l in all_laps if l.get("isValidForBest", False) and l.get("laptime", 2147483647) != 2147483647]
        
        if valid_laps:
            lap_times = [l["laptime"] for l in valid_laps]
            
            # Estatísticas de tempo
            fastest_lap = min(lap_times)
            slowest_lap = max(lap_times)
            avg_lap = sum(lap_times) / len(lap_times)
            
            # Métricas de consistência
            consistency_metrics = calculate_consistency_metrics(lap_times)
            
            # Top 10% voltas mais rápidas
            sorted_laps = sorted(lap_times)
            top_10_percent_count = max(1, len(sorted_laps) // 10)
            top_10_avg = sum(sorted_laps[:top_10_percent_count]) / top_10_percent_count
            
            stats.update({
                "fastest_lap": fastest_lap,
                "fastest_lap_formatted": format_time_ms(fastest_lap),
                "slowest_lap": slowest_lap,
                "slowest_lap_formatted": format_time_ms(slowest_lap),
                "avg_lap": avg_lap,
                "avg_lap_formatted": format_time_ms(int(avg_lap)),
                "consistency": consistency_metrics["std_dev"],
                "consistency_formatted": consistency_metrics["std_dev_formatted"],
                "avg_gap_from_best": consistency_metrics["avg_gap_from_best"],
                "avg_gap_from_best_formatted": consistency_metrics["avg_gap_from_best_formatted"],
                "max_variation": consistency_metrics["max_variation"],
                "max_variation_formatted": consistency_metrics["max_variation_formatted"],
                "consistency_ratio": consistency_metrics["consistency_ratio"],
                "consistency_ratio_formatted": consistency_metrics["consistency_ratio_formatted"],
                "top_10_avg": top_10_avg,
                "top_10_avg_formatted": format_time_ms(int(top_10_avg)),
                "total_valid_laps": len(valid_laps),
                "total_invalid_laps": len(all_laps) - len(valid_laps),
            })
    
    return stats


def analyze_driver_laps(all_laps, car_id):
    """Analisa voltas de um piloto específico e retorna estatísticas detalhadas"""
    driver_laps = [l for l in all_laps if l.get("carId") == car_id]
    
    if not driver_laps:
        return None
    
    valid_laps = [l for l in driver_laps if l.get("isValidForBest", False) and l.get("laptime", 2147483647) != 2147483647]
    
    if not valid_laps:
        return {
            "total_laps": len(driver_laps),
            "valid_laps": 0,
            "invalid_laps": len(driver_laps),
        }
    
    lap_times = [l["laptime"] for l in valid_laps]
    splits_data = [l.get("splits", []) for l in valid_laps]
    
    # Estatísticas básicas
    fastest_lap = min(lap_times)
    slowest_lap = max(lap_times)
    avg_lap = sum(lap_times) / len(lap_times)
    
    # Métricas de consistência
    consistency_metrics = calculate_consistency_metrics(lap_times)
    
    # Melhor volta com setores
    best_lap_idx = lap_times.index(fastest_lap)
    best_lap_splits = splits_data[best_lap_idx] if best_lap_idx < len(splits_data) else []
    
    # Última volta
    last_lap = driver_laps[-1]
    last_lap_time = last_lap.get("laptime", 2147483647)
    last_lap_splits = last_lap.get("splits", [])
    
    # Análise de setores
    sector_times = [[], [], []]
    for splits in splits_data:
        for i, split in enumerate(splits[:3]):
            if split != 2147483647:
                sector_times[i].append(split)
    
    best_sectors = []
    avg_sectors = []
    for i in range(3):
        if sector_times[i]:
            best_sectors.append(min(sector_times[i]))
            avg_sectors.append(sum(sector_times[i]) / len(sector_times[i]))
        else:
            best_sectors.append(None)
            avg_sectors.append(None)

    # Melhor volta teórica (soma dos melhores setores, mesmo de voltas diferentes)
    if all(s is not None for s in best_sectors):
        best_possible_lap_ms = int(sum(best_sectors))
        best_possible_lap_formatted = format_time_ms(best_possible_lap_ms)
    else:
        best_possible_lap_ms = None
        best_possible_lap_formatted = "---"

    # Evolução de tempos (para gráfico)
    lap_evolution = []
    for idx, lap in enumerate(valid_laps):
        lap_evolution.append({
            "lap": idx + 1,
            "time": lap["laptime"],
            "time_formatted": format_time_ms(lap["laptime"]),
        })
    
    return {
        "total_laps": len(driver_laps),
        "valid_laps": len(valid_laps),
        "invalid_laps": len(driver_laps) - len(valid_laps),
        "fastest_lap": fastest_lap,
        "fastest_lap_formatted": format_time_ms(fastest_lap),
        "slowest_lap": slowest_lap,
        "slowest_lap_formatted": format_time_ms(slowest_lap),
        "avg_lap": avg_lap,
        "avg_lap_formatted": format_time_ms(int(avg_lap)),
        "consistency": consistency_metrics["std_dev"],
        "consistency_formatted": consistency_metrics["std_dev_formatted"],
        "avg_gap_from_best": consistency_metrics["avg_gap_from_best"],
        "avg_gap_from_best_formatted": consistency_metrics["avg_gap_from_best_formatted"],
        "max_variation": consistency_metrics["max_variation"],
        "max_variation_formatted": consistency_metrics["max_variation_formatted"],
        "consistency_ratio": consistency_metrics["consistency_ratio"],
        "consistency_ratio_formatted": consistency_metrics["consistency_ratio_formatted"],
        "best_lap_splits": best_lap_splits,
        "best_lap_splits_formatted": [format_time_ms(s) for s in best_lap_splits],
        "last_lap_time": last_lap_time,
        "last_lap_time_formatted": format_time_ms(last_lap_time),
        "last_lap_splits": last_lap_splits,
        "last_lap_splits_formatted": [format_time_ms(s) for s in last_lap_splits],
        "best_sectors": best_sectors,
        "best_sectors_formatted": [format_time_ms(s) if s else "---" for s in best_sectors],
        "avg_sectors": avg_sectors,
        "avg_sectors_formatted": [format_time_ms(int(s)) if s else "---" for s in avg_sectors],
        "best_possible_lap_ms": best_possible_lap_ms,
        "best_possible_lap_formatted": best_possible_lap_formatted,
        "lap_evolution": lap_evolution,
    }


def enrich_leaderboard_data(leaderboard):
    best_lap_session = None
    best_sectors = [None, None, None]
    
    for entry in leaderboard:
        timing = entry.get("timing", {})
        best_lap = timing.get("bestLap", 2147483647)
        if best_lap != 2147483647:
            if best_lap_session is None or best_lap < best_lap_session:
                best_lap_session = best_lap
        
        splits = timing.get("bestSplits", [])
        for i, split in enumerate(splits[:3]):
            if split != 2147483647:
                if best_sectors[i] is None or split < best_sectors[i]:
                    best_sectors[i] = split
    
    p1_total_time = leaderboard[0].get("timing", {}).get("totalTime", 0) if leaderboard else 0
    
    enriched = []
    for idx, entry in enumerate(leaderboard):
        entry_copy = dict(entry)
        timing = entry_copy.get("timing", {})
        car = entry_copy.get("car", {})
        
        best_lap = timing.get("bestLap", 2147483647)
        total_time = timing.get("totalTime", 0)
        splits = timing.get("bestSplits", [])
        
        gap = (total_time - p1_total_time) if p1_total_time and idx > 0 else 0
        if best_lap == 2147483647:
            gap = 0
        
        entry_copy["gap"] = gap
        entry_copy["gap_formatted"] = format_time_ms(gap) if gap > 0 else "---"
        entry_copy["best_lap_formatted"] = format_time_ms(best_lap)
        entry_copy["total_time_formatted"] = format_time_ms(total_time)
        entry_copy["splits_formatted"] = [format_time_ms(s) for s in splits]
        entry_copy["car_name"] = get_car_name(car.get("carModel", -1))
        entry_copy["car_class"] = get_car_class(car.get("carModel", -1))
        entry_copy["track_display"] = ""
        
        entry_copy["is_best_lap"] = (best_lap == best_lap_session and best_lap != 2147483647)
        
        sector_classes = []
        for i, split in enumerate(splits[:3]):
            if split == 2147483647:
                sector_classes.append("neutral")
            elif best_sectors[i] is not None and split == best_sectors[i]:
                sector_classes.append("best")
            else:
                sector_classes.append("normal")
        entry_copy["sector_classes"] = sector_classes
        
        enriched.append(entry_copy)
    
    return enriched, best_lap_session, best_sectors


def organize_laps_by_driver(all_laps, leaderboard):
    if not all_laps:
        return {}
    
    driver_laps = {}
    
    for lap in all_laps:
        car_id = lap.get("carId")
        driver_idx = lap.get("driverIndex", 0)
        key = f"{car_id}_{driver_idx}"
        
        if key not in driver_laps:
            driver_laps[key] = {
                "car_id": car_id,
                "driver_index": driver_idx,
                "laps": []
            }
        
        laptime = lap.get("laptime", 0)
        splits = lap.get("splits", [])
        is_valid = lap.get("isValidForBest", True)
        
        driver_laps[key]["laps"].append({
            "lap_number": len(driver_laps[key]["laps"]) + 1,
            "laptime": laptime,
            "laptime_formatted": format_time_ms(laptime),
            "splits": splits,
            "splits_formatted": [format_time_ms(s) for s in splits],
            "is_valid": is_valid,
        })
    
    for key, data in driver_laps.items():
        valid_laps = [l for l in data["laps"] if l["is_valid"] and l["laptime"] != 2147483647]
        if valid_laps:
            best_lap = min(valid_laps, key=lambda x: x["laptime"])
            data["best_lap"] = best_lap["laptime_formatted"]
            data["best_lap_ms"] = best_lap["laptime"]
            data["best_lap_number"] = best_lap["lap_number"]
            data["best_lap_splits"] = best_lap["splits"]
            data["best_lap_splits_formatted"] = best_lap["splits_formatted"]
            
            avg_time = sum(l["laptime"] for l in valid_laps) / len(valid_laps)
            data["avg_lap"] = format_time_ms(int(avg_time))
            
            # Métricas de consistência
            times = [l["laptime"] for l in valid_laps]
            consistency_metrics = calculate_consistency_metrics(times)
            data["consistency"] = consistency_metrics["std_dev_formatted"]
            data["avg_gap_from_best"] = consistency_metrics["avg_gap_from_best_formatted"]
            data["max_variation"] = consistency_metrics["max_variation_formatted"]
            data["consistency_ratio"] = consistency_metrics["consistency_ratio_formatted"]
            
            # Melhores setores individuais (podem vir de voltas diferentes)
            best_sectors = [None, None, None]
            for lap in valid_laps:
                splits = lap.get("splits", [])
                for i, split in enumerate(splits[:3]):
                    if split != 2147483647:
                        if best_sectors[i] is None or split < best_sectors[i]:
                            best_sectors[i] = split
            
            data["best_s1"] = format_time_ms(best_sectors[0]) if best_sectors[0] is not None else "---"
            data["best_s2"] = format_time_ms(best_sectors[1]) if best_sectors[1] is not None else "---"
            data["best_s3"] = format_time_ms(best_sectors[2]) if best_sectors[2] is not None else "---"
            data["best_s1_ms"] = best_sectors[0] if best_sectors[0] is not None else 2147483647
            data["best_s2_ms"] = best_sectors[1] if best_sectors[1] is not None else 2147483647
            data["best_s3_ms"] = best_sectors[2] if best_sectors[2] is not None else 2147483647

            # Melhor volta teórica (soma dos melhores setores, mesmo de voltas diferentes)
            if all(s is not None for s in best_sectors):
                best_possible_lap_ms = int(sum(best_sectors))
                data["best_possible_lap"] = format_time_ms(best_possible_lap_ms)
                data["best_possible_lap_ms"] = best_possible_lap_ms
            else:
                data["best_possible_lap"] = "---"
                data["best_possible_lap_ms"] = 2147483647
        else:
            data["best_lap"] = "---"
            data["best_lap_ms"] = 2147483647
            data["best_lap_number"] = None
            data["best_lap_splits"] = []
            data["best_lap_splits_formatted"] = ["---", "---", "---"]
            data["avg_lap"] = "---"
            data["consistency"] = "---"
            data["avg_gap_from_best"] = "---"
            data["max_variation"] = "---"
            data["consistency_ratio"] = "---"
            data["best_s1"] = "---"
            data["best_s2"] = "---"
            data["best_s3"] = "---"
            data["best_s1_ms"] = 2147483647
            data["best_s2_ms"] = 2147483647
            data["best_s3_ms"] = 2147483647
            data["best_possible_lap"] = "---"
            data["best_possible_lap_ms"] = 2147483647
        
        data["total_laps"] = len(data["laps"])
        data["valid_laps"] = len(valid_laps)
        data["invalid_laps"] = len(data["laps"]) - len(valid_laps)
    
    laps_by_car_id = {}
    for key, data in driver_laps.items():
        car_id = data["car_id"]
        laps_by_car_id[car_id] = data
    
    return laps_by_car_id


class LeaderBoard(tables.Table):
    position = Column(empty_values=())
    raceNumber = Column(accessor="car.raceNumber")
    carModel = Column(accessor="car.carModel")
    teamName = Column(accessor="car.teamName")
    drivers = Column(accessor="car.drivers")
    bestLap = Column(accessor="timing")
    laps = Column(accessor="timing.lapCount")
    totaltime = Column(accessor="timing.totalTime")

    def __init__(self, *args, **kwargs):
        super(LeaderBoard, self).__init__(*args, **kwargs)
        self.counter = itertools.count(start=1)

    def render_position(self):
        return "%d" % next(self.counter)

    def render_carModel(self, value):
        for model in CAR_MODEL_TYPES:
            if model[0] == value:
                return model[1]
        return "Unknown model %i" % value

    def render_drivers(self, value):
        short = " / ".join([d["shortName"] for d in value])
        long = " / ".join(["%s %s" % (d["firstName"], d["lastName"]) for d in value])
        return format_html("<p>({}) {}</p>", short, long)

    def render_time(self, value):
        if value == 2147483647:
            return "---"
        s = value // 1000
        m = s // 60
        s %= 60
        if m == 0:
            return "%02i.%03i" % (s, value % 1000)
        return "%i:%02i.%03i" % (m, s, value % 1000)

    def render_bestLap(self, value):
        return format_html(
            '<p title="{}">{}</p>',
            " | ".join(list(map(self.render_time, value["bestSplits"]))),
            self.render_time(value["bestLap"]),
        )

    def render_totaltime(self, value):
        return self.render_time(value)


class Results(tables.Table):
    display_name = Column(verbose_name="Session")
    type = Column(verbose_name="Type")
    track = Column()
    date = Column(verbose_name="Date")
    time = Column(verbose_name="Time")
    entries = Column()
    wetSession = Column(verbose_name="Wet")
    view = TemplateColumn(template_name="results/table/results_view_column.html")
    download = TemplateColumn(
        template_name="results/table/results_download_column.html"
    )
    simresults = TemplateColumn(
        template_name="results/table/results_simresults_column.html"
    )


class ResultsGlobal(tables.Table):
    instance = Column(verbose_name="Instance")
    display_name = Column(verbose_name="Session")
    type = Column(verbose_name="Type")
    track = Column()
    date = Column(verbose_name="Date")
    time = Column(verbose_name="Time")
    entries = Column()
    wetSession = Column(verbose_name="Wet")
    view = TemplateColumn(template_name="results/table/results_view_column.html")
    download = TemplateColumn(
        template_name="results/table/results_download_column.html"
    )
    simresults = TemplateColumn(
        template_name="results/table/results_simresults_column.html"
    )


def parse_url(args, kwargs):
    """Read the select results file and display the selected portion of the json object"""
    instance = kwargs["instance"]
    result = args[0]
    results_path = os.path.join(DATA_DIR, "instances", instance, "results")
    return os.path.join(results_path, result + ".json")


# Public page: session detail only (data already available via the public
# JSON endpoints used by simresults.net). Management views stay behind
# role_required.
def results(request, *args, **kwargs):
    """Read the select results file and display the selected portion of the json object"""
    results = json.load(open(parse_url(args, kwargs), "rb"))
    path = request.path
    if path[0] == "/":
        path = path[1:]
    if path[-1] == "/":
        path = path[:-1]
    path = path.split("/")

    session_result = results.get("sessionResult", {})
    leaderboard = session_result.get("leaderBoardLines", [])
    all_laps = results.get("laps", [])
    
    enriched_data, best_lap_session, best_sectors = enrich_leaderboard_data(leaderboard)
    session_stats = calculate_session_stats(leaderboard, all_laps)
    
    driver_laps_data = organize_laps_by_driver(all_laps, leaderboard)

    # Análise detalhada por piloto
    driver_analysis = {}
    for entry in leaderboard:
        car_id = entry.get("car", {}).get("carId")
        if car_id:
            analysis = analyze_driver_laps(all_laps, car_id)
            if analysis:
                driver_analysis[car_id] = analysis

    # Melhor "best possible lap" da sessão (melhor soma de setores entre todos os pilotos)
    session_best_possible_lap = None
    for data in driver_laps_data.values():
        bpl = data.get("best_possible_lap_ms")
        if bpl and bpl != 2147483647:
            if session_best_possible_lap is None or bpl < session_best_possible_lap:
                session_best_possible_lap = bpl

    session_stats["best_possible_lap"] = session_best_possible_lap
    session_stats["best_possible_lap_formatted"] = format_time_ms(session_best_possible_lap)

    track_code = results.get("trackName", "")
    track_name = get_track_name(track_code)

    session_type = results.get("sessionType", "R")
    session_type_map = {"P": "Practice", "Q": "Qualifying", "R": "Race", "FP": "Practice"}
    session_type_name = session_type_map.get(session_type, session_type)

    is_wet = session_result.get("isWetSession", 0)

    parsed = parse_session_name(args[0] if args else "")

    best_lap_driver = None
    if leaderboard and best_lap_session:
        for entry in leaderboard:
            if entry.get("timing", {}).get("bestLap") == best_lap_session:
                drivers = entry.get("car", {}).get("drivers", [])
                if drivers:
                    best_lap_driver = f"{drivers[0].get('firstName', '')} {drivers[0].get('lastName', '')}".strip()
                break

    best_sectors_formatted = [format_time_ms(s) if s and s != 2147483647 else "---" for s in best_sectors]

    # Informações adicionais da sessão
    server_name = results.get("serverName", "")
    race_weekend_index = results.get("raceWeekendIndex")
    
    context = {
        "path": [(j, "/" + "/".join(path[: i + 1])) for i, j in enumerate(path)],
        "table": LeaderBoard(leaderboard),
        "instance": kwargs["instance"],
        "title": args[0] if args else "Result",
        "is_detail": True,
        "public_page": True,
        "session_info": {
            "track_name": track_name,
            "track_code": track_code,
            "session_type": session_type,
            "session_type_name": session_type_name,
            "is_wet": is_wet,
            "date_str": parsed.get("date_str", ""),
            "time_str": parsed.get("time_str", ""),
            "best_lap_formatted": session_stats.get("best_lap_formatted", "---"),
            "best_lap_driver": best_lap_driver,
            "best_sectors": best_sectors_formatted,
            "best_possible_lap_formatted": session_stats.get("best_possible_lap_formatted", "---"),
            "server_name": server_name,
            "race_weekend_index": race_weekend_index,
        },
        "stats": session_stats,
        "leaderboard_data": enriched_data,
        "driver_laps": driver_laps_data,
        "driver_analysis": driver_analysis,
    }
    return render(request, "results/results.html", context)


@role_required("Admin", "Operator", "Viewer")
def download(request, *args, **kwargs):
    _f = parse_url(args, kwargs)
    print(_f, os.path.basename(_f))
    if _f is not None and os.path.isfile(_f):
        with open(_f, "rb") as fh:
            response = HttpResponse(fh.read(), content_type="text/plain")
            response["Content-Disposition"] = "inline; filename=" + os.path.basename(_f)
            return response
    raise Http404


def download_public(request, result, **kwargs):
    instance = kwargs.get("instance")
    results_path = os.path.join(DATA_DIR, "instances", instance, "results")
    _f = os.path.join(results_path, result + ".json")
    if os.path.isfile(_f):
        with open(_f, "rb") as fh:
            response = HttpResponse(fh.read(), content_type="text/plain")
            response["Content-Disposition"] = "inline; filename=" + os.path.basename(_f)
            return response
    raise Http404


def download_public_global(request, instance, result):
    results_path = os.path.join(DATA_DIR, "instances", instance, "results")
    _f = os.path.join(results_path, result + ".json")
    if os.path.isfile(_f):
        with open(_f, "rb") as fh:
            response = HttpResponse(fh.read(), content_type="text/plain")
            response["Content-Disposition"] = "inline; filename=" + os.path.basename(_f)
            return response
    raise Http404


DAY_OF_WEEKEND = {
    1: 'Fri',
    2: 'Sat',
    3: 'Sun',
}


def get_event_sessions(instance):
    """Lê o event.json da instância e retorna mapeamento de sessões"""
    event_path = os.path.join(DATA_DIR, "instances", instance, "cfg", "event.json")
    if not os.path.isfile(event_path):
        return {}
    
    try:
        with open(event_path, "rb") as f:
            event_data = json.load(f)
        
        sessions_map = {}
        for session in event_data.get("sessions", []):
            session_type = session.get("sessionType")
            day_of_weekend = session.get("dayOfWeekend")
            hour_of_day = session.get("hourOfDay")
            
            if session_type:
                key = f"{session_type}_{hour_of_day:02d}"
                sessions_map[key] = {
                    "day": DAY_OF_WEEKEND.get(day_of_weekend, ''),
                    "hour": hour_of_day,
                }
        
        return sessions_map
    except (json.JSONDecodeError, KeyError, TypeError, IOError):
        return {}


def get_race_day(session_type, hour_of_day, event_sessions):
    """Busca o dia da semana baseado no sessionType e hora"""
    key = f"{session_type}_{hour_of_day:02d}"
    if key in event_sessions:
        return event_sessions[key].get("day", '')
    
    type_map = {
        "FP": "P",
        "PRACTICE": "P",
        "QUALIFY": "Q",
        "QUALIFYING": "Q",
    }
    normalized_type = type_map.get(session_type, session_type)
    
    for key, info in event_sessions.items():
        if key.startswith(f"{normalized_type}_"):
            return info.get("day", '')
    
    return ''


# Public page: per-instance session listing only (same metadata as the
# global /results/ listing). Management views stay behind role_required.
def resultSelect(request, instance):
    """Show available results"""
    results_path = os.path.join(DATA_DIR, "instances", instance, "results")
    files = sorted(glob.glob("%s/*.json" % (results_path)), reverse=True)
    files = filter(lambda x: not x.endswith("entrylist.json"), files)
    
    event_sessions = get_event_sessions(instance)
    
    # Agrupar sessões por evento (raceWeekendIndex)
    events = {}
    all_sessions = []
    
    for f in files:
        try:
            r = json.load(open(f, "rb"))
            parsed = parse_session_name(os.path.splitext(ntpath.basename(f))[0])
            
            session_type = r.get("sessionType", "")
            hour = parsed.get("datetime")
            hour_of_day = hour.hour if hour else 0
            
            race_day = get_race_day(session_type, hour_of_day, event_sessions)
            race_weekend_index = r.get("raceWeekendIndex")
            
            session_data = dict(
                name=os.path.splitext(ntpath.basename(f))[0],
                display_name=parsed["display"],
                date=parsed["date_str"],
                time=parsed["time_str"],
                race_day=race_day,
                type=r["sessionType"],
                entries=len(r["sessionResult"]["leaderBoardLines"]),
                wetSession=r["sessionResult"]["isWetSession"],
                track=r["trackName"],
                instance=instance,
                race_weekend_index=race_weekend_index,
            )
            
            all_sessions.append(session_data)
            
            # Agrupar por evento
            if race_weekend_index is not None:
                if race_weekend_index not in events:
                    events[race_weekend_index] = {
                        'index': race_weekend_index,
                        'sessions': [],
                        'track': r["trackName"],
                        'date': parsed["date_str"],
                        'time': parsed["time_str"],
                    }
                events[race_weekend_index]['sessions'].append(session_data)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    
    # Converter events para lista ordenada
    events_list = sorted(events.values(), key=lambda e: e['index'], reverse=True)
    
    # Filtrar por evento se especificado
    selected_event = request.GET.get('event')
    filtered_sessions = all_sessions
    
    if selected_event is not None and selected_event != '':
        try:
            event_idx = int(selected_event)
            if event_idx in events:
                filtered_sessions = events[event_idx]['sessions']
        except (ValueError, KeyError):
            pass

    path = request.path
    if path[0] == "/":
        path = path[1:]
    if path[-1] == "/":
        path = path[:-1]
    path = path.split("/")

    table = Results(filtered_sessions)
    RequestConfig(request).configure(table)

    context = {
        "path": [(j, "/" + "/".join(path[: i + 1])) for i, j in enumerate(path)],
        "table": table,
        "sessions": filtered_sessions,
        "events": events_list,
        "selected_event": selected_event,
        "instance": instance,
        "title": "Results",
        "is_detail": False,
        "public_page": True,
    }
    return render(request, "results/results.html", context)


# Public page: session listing only. Detail/download views stay behind
# role_required, so anonymous users cannot reach any other data.
def all_results(request):
    from accservermanager.settings import DATA_DIR

    instances_dir = os.path.join(DATA_DIR, "instances")
    all_items = []
    event_sessions_cache = {}
    for inst_dir in sorted(glob.glob(os.path.join(instances_dir, "*"))):
        if not os.path.isdir(inst_dir):
            continue
        inst_name = os.path.basename(inst_dir)
        results_path = os.path.join(inst_dir, "results")
        if not os.path.isdir(results_path):
            continue
        if inst_name not in event_sessions_cache:
            event_sessions_cache[inst_name] = get_event_sessions(inst_name)
        event_sessions = event_sessions_cache[inst_name]
        files = sorted(glob.glob(os.path.join(results_path, "*.json")), reverse=True)
        files = [f for f in files if not f.endswith("entrylist.json")]
        for f in files:
            try:
                r = json.load(open(f, "rb"))
                parsed = parse_session_name(os.path.splitext(ntpath.basename(f))[0])
                session_type = r.get("sessionType", "")
                hour = parsed.get("datetime")
                hour_of_day = hour.hour if hour else 0
                race_day = get_race_day(session_type, hour_of_day, event_sessions)
                race_weekend_index = r.get("raceWeekendIndex")
                all_items.append(
                    dict(
                        instance=inst_name,
                        name=os.path.splitext(ntpath.basename(f))[0],
                        display_name=parsed["display"],
                        date=parsed["date_str"],
                        time=parsed["time_str"],
                        race_day=race_day,
                        type=r["sessionType"],
                        entries=len(r["sessionResult"]["leaderBoardLines"]),
                        wetSession=r["sessionResult"]["isWetSession"],
                        track=r["trackName"],
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

    all_items.sort(key=lambda x: x.get("name", ""), reverse=True)
    table = ResultsGlobal(all_items)
    RequestConfig(request).configure(table)
    context = {
        "path": [("Results", "/results/")],
        "table": table,
        "sessions": all_items,
        "instance": None,
        "title": "Results",
        "is_detail": False,
        "is_global": True,
        "public_page": True,
    }
    return render(request, "results/results.html", context)
