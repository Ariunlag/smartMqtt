import axios from "axios";
import type { DupeListResponse, DupeRecord, ConfirmDupeRequest } from "../types/api_models";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

export const getDuplicates = () =>
  axios.get<DupeListResponse>(`${BASE_URL}/duplicates`);

export const confirmDuplicate = (req: ConfirmDupeRequest) =>
  axios.post<DupeRecord>(`${BASE_URL}/duplicate-confirm`, req);
