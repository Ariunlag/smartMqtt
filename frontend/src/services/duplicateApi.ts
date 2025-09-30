import axios from "axios";
import type { DupeListResponse, DupeRecord, ConfirmDupeRequest } from "../types/api_models";

const BASE_URL = "http://localhost:8000/api";

export const getDuplicates = () =>
  axios.get<DupeListResponse>(`${BASE_URL}/duplicates`);

export const confirmDuplicate = (req: ConfirmDupeRequest) =>
  axios.post<DupeRecord>(`${BASE_URL}/duplicate-confirm`, req);
