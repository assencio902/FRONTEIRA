// Serviço de watchlist (stub básico)
class WatchlistService {
  final Set<String> _watchedPlates = {};
  
  Future<void> init() async {
    // TODO: Carregar placas salvas do armazenamento local
  }
  
  bool isInWatchlist(String plate) {
    return _watchedPlates.contains(plate.toUpperCase());
  }
  
  Future<List<String>> getWatchedPlates() async {
    return _watchedPlates.toList();
  }
  
  Future<void> addPlate(String plate) async {
    _watchedPlates.add(plate.toUpperCase());
    // TODO: Salvar no armazenamento local
  }
  
  Future<void> removePlate(String plate) async {
    _watchedPlates.remove(plate.toUpperCase());
    // TODO: Salvar no armazenamento local
  }
}
